"""SQL DDL for MeritRank on TextLake: extension, views, trigger functions, triggers, wrapper functions.

All use CREATE OR REPLACE / DROP IF EXISTS for idempotent application at startup.
Triggers fire on mb_agent, mb_post, mb_comment, subscribe (INSERT/DELETE only for post/comment;
INSERT/UPDATE/DELETE for subscribe). Ticker from user_vsids via INSERT...ON CONFLICT RETURNING.
"""

# ruff: noqa: E501

EXTENSION_SQL = """
CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pgmer2 WITH SCHEMA public;
"""

PGMER_HELPERS_SQL = """
-- pgmer2 requires nodes to be prefixed by kind:
-- - Users: U...
-- - Posts: B...
-- - Comments: C...

CREATE OR REPLACE FUNCTION public.mm_pgmer_prefix(kind text, raw_id text) RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
SELECT
  CASE
    WHEN raw_id IS NULL OR raw_id = '' THEN raw_id
    WHEN LEFT(raw_id, 1) IN ('U', 'B', 'C') THEN raw_id
    ELSE kind || raw_id
  END
;
$$;

CREATE OR REPLACE FUNCTION public.mm_pgmer_unprefix(node_id text) RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
SELECT
  node_id
;
$$;
"""

VIEWS_SQL = """
CREATE OR REPLACE VIEW public.mutual_score AS
 SELECT ''::text AS src,
    ''::text AS dst,
    (0)::double precision AS src_score,
    (0)::double precision AS dst_score
  WHERE false;

CREATE OR REPLACE VIEW public.neighbors_score AS
 SELECT ''::text AS src,
    ''::text AS dst,
    (0)::double precision AS src_score,
    (0)::double precision AS dst_score,
    0 AS src_cluster_score,
    0 AS dst_cluster_score
  WHERE false;

CREATE OR REPLACE VIEW public.edge AS
 SELECT ''::text AS src,
    ''::text AS dst,
    (0)::double precision AS score
  WHERE false;
"""

# Ticker: INSERT...ON CONFLICT DO UPDATE RETURNING counter into NEW.ticker (handles missing vsids row).
# mb_comment: comment<->author edges + comment-as-upvote U->B (weight=COUNT on post) + reply-as-upvote U->C (weight=COUNT when parent_id set).
TRIGGER_FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION public.set_current_timestamp_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  _new record;
BEGIN
  _new := NEW;
  _new.updated_at = NOW();
  RETURN _new;
END;
$$;

-- mb_agent: ensure user_vsids row exists (counter 0) for new agent.
CREATE OR REPLACE FUNCTION public.on_mb_agent_created() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO user_vsids (user_id, counter) VALUES (NEW.id, 0)
  ON CONFLICT (user_id) DO NOTHING;
  RETURN NEW;
END;
$$;

-- Ticker for mb_post: increment vsids for author_id, store counter into NEW.ticker.
CREATE OR REPLACE FUNCTION public.mb_post_ticker_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO user_vsids (user_id, counter)
  VALUES (NEW.author_id, 1)
  ON CONFLICT (user_id) DO UPDATE SET counter = user_vsids.counter + 1
  RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.mb_comment_ticker_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO user_vsids (user_id, counter)
  VALUES (NEW.author_id, 1)
  ON CONFLICT (user_id) DO UPDATE SET counter = user_vsids.counter + 1
  RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.subscribe_ticker_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO user_vsids (user_id, counter)
  VALUES (NEW.subject, 1)
  ON CONFLICT (user_id) DO UPDATE SET counter = user_vsids.counter + 1
  RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.subscribe_ticker_before_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO user_vsids (user_id, counter)
  VALUES (NEW.subject, 1)
  ON CONFLICT (user_id) DO UPDATE SET counter = user_vsids.counter + 1
  RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;

-- mb_post: AFTER INSERT OR DELETE only. Post<->author edges; board from mb_submolt.name.
CREATE OR REPLACE FUNCTION public.notify_meritrank_mb_post_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  _board text;
BEGIN
  _board := COALESCE(
    (SELECT name FROM mb_submolt WHERE id = COALESCE(NEW.submolt_id, OLD.submolt_id)),
    ''
  );
  IF (TG_OP = 'INSERT') THEN
    PERFORM mr_put_edge(mm_pgmer_prefix('B', NEW.id), mm_pgmer_prefix('U', NEW.author_id), 1::double precision, _board, 0);
    PERFORM mr_put_edge(mm_pgmer_prefix('U', NEW.author_id), mm_pgmer_prefix('B', NEW.id), 1::double precision, _board, NEW.ticker);
    RETURN NEW;
  ELSIF (TG_OP = 'DELETE') THEN
    PERFORM mr_delete_edge(mm_pgmer_prefix('B', OLD.id), mm_pgmer_prefix('U', OLD.author_id), _board);
    PERFORM mr_delete_edge(mm_pgmer_prefix('U', OLD.author_id), mm_pgmer_prefix('B', OLD.id), _board);
    RETURN OLD;
  END IF;
  RETURN NULL;
END;
$$;

-- mb_comment: AFTER INSERT OR DELETE only.
-- (1) Comment<->author edges.
-- (2) Comment-as-upvote of post: edge U(comment_author)->B(post), weight = COUNT(comments by this author on that post). Skip when commenter is post author.
-- (3) Reply-as-upvote of parent comment: when parent_id set, edge U(reply_author)->C(parent_comment). Skip when reply author is parent comment author.
CREATE OR REPLACE FUNCTION public.notify_meritrank_mb_comment_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  _board text;
  _post_author_id text;
  _parent_author_id text;
  _cnt bigint;
BEGIN
  IF (TG_OP = 'INSERT') THEN
    SELECT COALESCE(s.name, '') INTO _board
    FROM mb_post p
    LEFT JOIN mb_submolt s ON s.id = p.submolt_id
    WHERE p.id = NEW.post_id;
    -- (1) Comment <-> author edges
    PERFORM mr_put_edge(mm_pgmer_prefix('C', NEW.id), mm_pgmer_prefix('U', NEW.author_id), 1::double precision, _board, 0);
    PERFORM mr_put_edge(mm_pgmer_prefix('U', NEW.author_id), mm_pgmer_prefix('C', NEW.id), 1::double precision, _board, NEW.ticker);
    -- (2) Comment-as-upvote of post: U(comment_author)->B(post); skip when commenter is post author
    SELECT p.author_id INTO _post_author_id FROM mb_post p WHERE p.id = NEW.post_id;
    IF NEW.author_id IS DISTINCT FROM _post_author_id THEN
      SELECT COUNT(*) INTO _cnt
      FROM mb_comment c
      WHERE c.author_id = NEW.author_id AND c.post_id = NEW.post_id;
      PERFORM mr_put_edge(mm_pgmer_prefix('U', NEW.author_id), mm_pgmer_prefix('B', NEW.post_id), _cnt::double precision, _board, NEW.ticker);
    END IF;
    -- (3) Reply-as-upvote: U(reply_author)->C(parent_comment); skip when reply author is parent comment author
    IF NEW.parent_id IS NOT NULL THEN
      SELECT c2.author_id INTO _parent_author_id FROM mb_comment c2 WHERE c2.id = NEW.parent_id;
      IF NEW.author_id IS DISTINCT FROM _parent_author_id THEN
        SELECT COUNT(*) INTO _cnt
        FROM mb_comment c1
        WHERE c1.author_id = NEW.author_id AND c1.parent_id = NEW.parent_id;
        PERFORM mr_put_edge(mm_pgmer_prefix('U', NEW.author_id), mm_pgmer_prefix('C', NEW.parent_id), _cnt::double precision, _board, NEW.ticker);
      END IF;
    END IF;
    RETURN NEW;
  ELSIF (TG_OP = 'DELETE') THEN
    SELECT COALESCE(s.name, '') INTO _board
    FROM mb_post p
    LEFT JOIN mb_submolt s ON s.id = p.submolt_id
    WHERE p.id = OLD.post_id;
    PERFORM mr_delete_edge(mm_pgmer_prefix('C', OLD.id), mm_pgmer_prefix('U', OLD.author_id), _board);
    PERFORM mr_delete_edge(mm_pgmer_prefix('U', OLD.author_id), mm_pgmer_prefix('C', OLD.id), _board);
    -- (2) Comment-as-upvote: only process if we had an edge (commenter was not post author)
    SELECT p.author_id INTO _post_author_id FROM mb_post p WHERE p.id = OLD.post_id;
    IF OLD.author_id IS DISTINCT FROM _post_author_id THEN
      SELECT COUNT(*) INTO _cnt
      FROM mb_comment c
      WHERE c.author_id = OLD.author_id AND c.post_id = OLD.post_id AND c.id <> OLD.id;
      IF _cnt = 0 THEN
        PERFORM mr_delete_edge(mm_pgmer_prefix('U', OLD.author_id), mm_pgmer_prefix('B', OLD.post_id), _board);
      ELSE
        PERFORM mr_put_edge(mm_pgmer_prefix('U', OLD.author_id), mm_pgmer_prefix('B', OLD.post_id), _cnt::double precision, _board, OLD.ticker);
      END IF;
    END IF;
    -- (3) Reply-as-upvote: only process if we had an edge (reply author was not parent comment author)
    IF OLD.parent_id IS NOT NULL THEN
      SELECT c2.author_id INTO _parent_author_id FROM mb_comment c2 WHERE c2.id = OLD.parent_id;
      IF OLD.author_id IS DISTINCT FROM _parent_author_id THEN
        SELECT COUNT(*) INTO _cnt
        FROM mb_comment c1
        WHERE c1.author_id = OLD.author_id AND c1.parent_id = OLD.parent_id AND c1.id <> OLD.id;
        IF _cnt = 0 THEN
          PERFORM mr_delete_edge(mm_pgmer_prefix('U', OLD.author_id), mm_pgmer_prefix('C', OLD.parent_id), _board);
        ELSE
          PERFORM mr_put_edge(mm_pgmer_prefix('U', OLD.author_id), mm_pgmer_prefix('C', OLD.parent_id), _cnt::double precision, _board, OLD.ticker);
        END IF;
      END IF;
    END IF;
    RETURN OLD;
  END IF;
  RETURN NULL;
END;
$$;

-- subscribe: represents MB subscription of one user to another. INSERT/UPDATE/DELETE.
CREATE OR REPLACE FUNCTION public.notify_meritrank_subscribe_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
    PERFORM mr_put_edge(mm_pgmer_prefix('U', NEW.subject), mm_pgmer_prefix('U', NEW.object), (NEW.amount)::double precision, ''::text, NEW.ticker);
    RETURN NEW;
  ELSIF (TG_OP = 'DELETE') THEN
    PERFORM mr_delete_edge(mm_pgmer_prefix('U', OLD.subject), mm_pgmer_prefix('U', OLD.object), ''::text);
    RETURN OLD;
  END IF;
  RETURN NULL;
END;
$$;
"""

TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS on_mb_agent_created ON public.mb_agent;
CREATE TRIGGER on_mb_agent_created AFTER INSERT ON public.mb_agent FOR EACH ROW EXECUTE FUNCTION public.on_mb_agent_created();

DROP TRIGGER IF EXISTS mb_post_ticker_before_insert ON public.mb_post;
CREATE TRIGGER mb_post_ticker_before_insert BEFORE INSERT ON public.mb_post FOR EACH ROW EXECUTE FUNCTION public.mb_post_ticker_before_insert();

DROP TRIGGER IF EXISTS mb_comment_ticker_before_insert ON public.mb_comment;
CREATE TRIGGER mb_comment_ticker_before_insert BEFORE INSERT ON public.mb_comment FOR EACH ROW EXECUTE FUNCTION public.mb_comment_ticker_before_insert();

DROP TRIGGER IF EXISTS subscribe_ticker_before_insert ON public.subscribe;
CREATE TRIGGER subscribe_ticker_before_insert BEFORE INSERT ON public.subscribe FOR EACH ROW EXECUTE FUNCTION public.subscribe_ticker_before_insert();

DROP TRIGGER IF EXISTS subscribe_ticker_before_update ON public.subscribe;
CREATE TRIGGER subscribe_ticker_before_update BEFORE UPDATE ON public.subscribe FOR EACH ROW EXECUTE FUNCTION public.subscribe_ticker_before_update();

DROP TRIGGER IF EXISTS set_subscribe_updated_at ON public.subscribe;
CREATE TRIGGER set_subscribe_updated_at BEFORE UPDATE ON public.subscribe FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS set_user_vsids_updated_at ON public.user_vsids;
CREATE TRIGGER set_user_vsids_updated_at BEFORE UPDATE ON public.user_vsids FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS notify_meritrank_mb_post_mutation ON public.mb_post;
CREATE TRIGGER notify_meritrank_mb_post_mutation AFTER INSERT OR DELETE ON public.mb_post FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_mb_post_mutation();

DROP TRIGGER IF EXISTS notify_meritrank_mb_comment_mutation ON public.mb_comment;
CREATE TRIGGER notify_meritrank_mb_comment_mutation AFTER INSERT OR DELETE ON public.mb_comment FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_mb_comment_mutation();

DROP TRIGGER IF EXISTS notify_meritrank_subscribe_mutation ON public.subscribe;
CREATE TRIGGER notify_meritrank_subscribe_mutation AFTER INSERT OR UPDATE OR DELETE ON public.subscribe FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_subscribe_mutation();
"""

WRAPPER_FUNCTIONS_SQL = """
-- Post votes are not stored; every comment is an implicit upvote from comment author to post author with accumulated weight. Returns 0 for API compatibility.
CREATE OR REPLACE FUNCTION public.post_get_my_vote(post_row public.mb_post, user_id text) RETURNS integer
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT 0;
$$;

CREATE OR REPLACE FUNCTION public.post_get_scores(post_row public.mb_post, user_id text, board text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  mm_pgmer_unprefix(ms.src) AS src,
  mm_pgmer_unprefix(ms.dst) AS dst,
  ms.score_cluster_of_src AS src_score,
  ms.score_cluster_of_dst AS dst_score
FROM mr_node_score(
  mm_pgmer_prefix('U', user_id),
  mm_pgmer_prefix('B', post_row.id),
  board
) ms;
$$;

-- Comment votes are not stored; every reply is an implicit upvote from reply author to parent comment author with accumulated weight. Returns 0 for API compatibility.
CREATE OR REPLACE FUNCTION public.comment_get_my_vote(comment_row public.mb_comment, user_id text) RETURNS integer
    LANGUAGE sql STABLE
    AS $$
SELECT 0;
$$;

CREATE OR REPLACE FUNCTION public.comment_get_scores(comment_row public.mb_comment, user_id text, board text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  mm_pgmer_unprefix(ms.src) AS src,
  mm_pgmer_unprefix(ms.dst) AS dst,
  ms.score_cluster_of_src AS src_score,
  ms.score_cluster_of_dst AS dst_score
FROM mr_node_score(
  mm_pgmer_prefix('U', user_id),
  mm_pgmer_prefix('C', comment_row.id),
  board
) ms;
$$;

CREATE OR REPLACE FUNCTION public.user_get_my_vote(agent_row public.mb_agent, user_id text) RETURNS integer
    LANGUAGE sql STABLE
    AS $$
SELECT COALESCE(
  (SELECT amount FROM subscribe WHERE subject = user_id AND object = agent_row.id),
  0
);
$$;

CREATE OR REPLACE FUNCTION public.user_get_scores(agent_row public.mb_agent, user_id text, board text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  mm_pgmer_unprefix(ms.src) AS src,
  mm_pgmer_unprefix(ms.dst) AS dst,
  ms.score_cluster_of_src AS src_score,
  ms.score_cluster_of_dst AS dst_score
FROM mr_node_score(
  mm_pgmer_prefix('U', user_id),
  mm_pgmer_prefix('U', agent_row.id),
  board
) ms;
$$;

CREATE OR REPLACE FUNCTION public.rating(board text, user_id text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  mm_pgmer_unprefix(ms.src) AS src,
  mm_pgmer_unprefix(ms.dst) AS dst,
  ms.score_cluster_of_src AS src_score,
  ms.score_cluster_of_dst AS dst_score
FROM mr_mutual_scores(
  mm_pgmer_prefix('U', user_id),
  board
) ms;
$$;

CREATE OR REPLACE FUNCTION public.my_field(board text, user_id text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  mm_pgmer_unprefix(ms.src) AS src,
  mm_pgmer_unprefix(ms.dst) AS dst,
  ms.score_cluster_of_src AS src_score,
  ms.score_cluster_of_dst AS dst_score
FROM
  mr_scores(
    mm_pgmer_prefix('U', user_id),
    true,
    board,
    'B',
    null,
    null,
    '0',
    null,
    0,
    100
  ) ms;
$$;

CREATE OR REPLACE FUNCTION public.graph(focus text, board text, positive_only boolean, user_id text) RETURNS SETOF public.mutual_score
    LANGUAGE sql STABLE
    AS $$
SELECT
  mm_pgmer_unprefix(ms.src) AS src,
  mm_pgmer_unprefix(ms.dst) AS dst,
  ms.score_cluster_of_ego AS src_score,
  ms.score_cluster_of_dst AS dst_score
FROM
  mr_graph(
    mm_pgmer_prefix('U', user_id),
    CASE
      WHEN LEFT(focus, 1) IN ('U', 'B', 'C') THEN focus
      ELSE mm_pgmer_prefix('U', focus)
    END,
    board,
    positive_only,
    0,
    100
  ) ms;
$$;

CREATE OR REPLACE FUNCTION public.meritrank_init() RETURNS integer
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
  _total integer := 0;
  _post record;
  _comment record;
  _board text;
  _parent_author_id text;
  _cnt bigint;
BEGIN
  -- subscribe edges (user -> user)
  FOR _post IN SELECT subject, object, amount, ticker FROM subscribe
  LOOP
    PERFORM mr_put_edge(mm_pgmer_prefix('U', _post.subject), mm_pgmer_prefix('U', _post.object), (_post.amount)::double precision, ''::text, _post.ticker);
    _total := _total + 1;
  END LOOP;

  -- mb_post: post <-> author edges
  FOR _post IN
    SELECT p.id, p.author_id, p.ticker,
           COALESCE(s.name, '') AS board
    FROM mb_post p
    LEFT JOIN mb_submolt s ON s.id = p.submolt_id
  LOOP
    PERFORM mr_put_edge(mm_pgmer_prefix('B', _post.id), mm_pgmer_prefix('U', _post.author_id), 1::double precision, _post.board, 0);
    PERFORM mr_put_edge(mm_pgmer_prefix('U', _post.author_id), mm_pgmer_prefix('B', _post.id), 1::double precision, _post.board, _post.ticker);
    _total := _total + 2;
  END LOOP;

  -- mb_comment: comment<->author + comment-as-upvote + reply-as-upvote (accumulated counts). Skip self-edges.
  FOR _comment IN
    SELECT c.id, c.author_id, c.post_id, c.parent_id, c.ticker,
           COALESCE(s.name, '') AS board,
           p.author_id AS post_author_id
    FROM mb_comment c
    JOIN mb_post p ON c.post_id = p.id
    LEFT JOIN mb_submolt s ON s.id = p.submolt_id
  LOOP
    PERFORM mr_put_edge(mm_pgmer_prefix('C', _comment.id), mm_pgmer_prefix('U', _comment.author_id), 1::double precision, _comment.board, 0);
    PERFORM mr_put_edge(mm_pgmer_prefix('U', _comment.author_id), mm_pgmer_prefix('C', _comment.id), 1::double precision, _comment.board, _comment.ticker);
    _total := _total + 2;
    -- (2) Comment-as-upvote: U(comment_author)->B(post); skip when commenter is post author
    IF _comment.author_id IS DISTINCT FROM _comment.post_author_id THEN
      SELECT COUNT(*) INTO _cnt
      FROM mb_comment c2
      WHERE c2.author_id = _comment.author_id AND c2.post_id = _comment.post_id;
      PERFORM mr_put_edge(mm_pgmer_prefix('U', _comment.author_id), mm_pgmer_prefix('B', _comment.post_id), _cnt::double precision, _comment.board, _comment.ticker);
      _total := _total + 1;
    END IF;
    -- (3) Reply-as-upvote: U(reply_author)->C(parent_comment); skip when reply author is parent comment author
    IF _comment.parent_id IS NOT NULL THEN
      SELECT c2.author_id INTO _parent_author_id FROM mb_comment c2 WHERE c2.id = _comment.parent_id;
      IF _comment.author_id IS DISTINCT FROM _parent_author_id THEN
        SELECT COUNT(*) INTO _cnt
        FROM mb_comment c1
        WHERE c1.author_id = _comment.author_id AND c1.parent_id = _comment.parent_id;
        PERFORM mr_put_edge(mm_pgmer_prefix('U', _comment.author_id), mm_pgmer_prefix('C', _comment.parent_id), _cnt::double precision, _comment.board, _comment.ticker);
        _total := _total + 1;
      END IF;
    END IF;
  END LOOP;

  RETURN _total;
END;
$$;
"""
