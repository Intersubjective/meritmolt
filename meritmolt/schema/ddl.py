"""SQL DDL for MeritRank on TextLake: extension, types, trigger functions, triggers, wrapper functions.

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

CREATE OR REPLACE FUNCTION public.bump_vsids(p_user_id text) RETURNS integer
    LANGUAGE sql
    AS $$
INSERT INTO user_vsids (user_id, counter)
VALUES (p_user_id, 1)
ON CONFLICT (user_id) DO UPDATE SET counter = user_vsids.counter + 1
RETURNING counter;
$$;

CREATE OR REPLACE FUNCTION public.mm_get_board(p_submolt_id text) RETURNS text
    LANGUAGE sql STABLE
    AS $$
SELECT COALESCE((SELECT name FROM mb_submolt WHERE id = p_submolt_id), '');
$$;
"""

TYPES_SQL = """
DO $$ BEGIN
  CREATE TYPE public.mutual_score AS (src text, dst text, src_score double precision, dst_score double precision);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""

# ---- Trigger functions ----
TRIGGER_FUNCTIONS_SQL = """
-- ========== updated_at timestamp ==========
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

-- ========== mb_agent: ensure user_vsids row exists (counter 0) for new agent ==========
CREATE OR REPLACE FUNCTION public.on_mb_agent_created() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO user_vsids (user_id, counter) VALUES (NEW.id, 0)
  ON CONFLICT (user_id) DO NOTHING;
  RETURN NEW;
END;
$$;

-- ========== Ticker triggers (author_id for post/comment, subject for subscribe) ==========
CREATE OR REPLACE FUNCTION public.author_id_ticker_trigger() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.ticker := bump_vsids(NEW.author_id);
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.subject_ticker_trigger() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.ticker := bump_vsids(NEW.subject);
  RETURN NEW;
END;
$$;

-- ========== Comment-as-upvote U->B, Reply-as-upvote U->C (p_exclude_id for DELETE) ==========
CREATE OR REPLACE FUNCTION public.mm_sync_comment_upvote_edge(
  p_author_id text, p_post_id text, p_board text, p_ticker integer, p_exclude_id text DEFAULT NULL
) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
  _post_author_id text;
  _cnt bigint;
BEGIN
  SELECT author_id INTO _post_author_id FROM mb_post WHERE id = p_post_id;
  IF p_author_id IS DISTINCT FROM _post_author_id THEN
    SELECT COUNT(*) INTO _cnt
    FROM mb_comment c
    WHERE c.author_id = p_author_id AND c.post_id = p_post_id
      AND (p_exclude_id IS NULL OR c.id <> p_exclude_id);
    IF _cnt = 0 THEN
      PERFORM mr_delete_edge(mm_pgmer_prefix('U', p_author_id), mm_pgmer_prefix('B', p_post_id), p_board);
    ELSE
      PERFORM mr_put_edge(mm_pgmer_prefix('U', p_author_id), mm_pgmer_prefix('B', p_post_id), _cnt::double precision, p_board, p_ticker);
    END IF;
    RETURN 1;
  END IF;
  RETURN 0;
END;
$$;

CREATE OR REPLACE FUNCTION public.mm_sync_reply_upvote_edge(
  p_author_id text, p_parent_id text, p_board text, p_ticker integer, p_exclude_id text DEFAULT NULL
) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
  _parent_author_id text;
  _cnt bigint;
BEGIN
  SELECT author_id INTO _parent_author_id FROM mb_comment WHERE id = p_parent_id;
  IF p_author_id IS DISTINCT FROM _parent_author_id THEN
    SELECT COUNT(*) INTO _cnt
    FROM mb_comment c
    WHERE c.author_id = p_author_id AND c.parent_id = p_parent_id
      AND (p_exclude_id IS NULL OR c.id <> p_exclude_id);
    IF _cnt = 0 THEN
      PERFORM mr_delete_edge(mm_pgmer_prefix('U', p_author_id), mm_pgmer_prefix('C', p_parent_id), p_board);
    ELSE
      PERFORM mr_put_edge(mm_pgmer_prefix('U', p_author_id), mm_pgmer_prefix('C', p_parent_id), _cnt::double precision, p_board, p_ticker);
    END IF;
    RETURN 1;
  END IF;
  RETURN 0;
END;
$$;

-- ========== MeritRank edge mutation: mb_post, mb_comment, subscribe ==========
CREATE OR REPLACE FUNCTION public.notify_meritrank_mb_post_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  _board text;
BEGIN
  _board := mm_get_board(COALESCE(NEW.submolt_id, OLD.submolt_id));
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
-- (1) Comment<->author edges. (2) Comment-as-upvote U->B. (3) Reply-as-upvote U->C.
CREATE OR REPLACE FUNCTION public.notify_meritrank_mb_comment_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  _board text;
BEGIN
  IF (TG_OP = 'INSERT') THEN
    _board := mm_get_board((SELECT submolt_id FROM mb_post WHERE id = NEW.post_id));
    PERFORM mr_put_edge(mm_pgmer_prefix('C', NEW.id), mm_pgmer_prefix('U', NEW.author_id), 1::double precision, _board, 0);
    PERFORM mr_put_edge(mm_pgmer_prefix('U', NEW.author_id), mm_pgmer_prefix('C', NEW.id), 1::double precision, _board, NEW.ticker);
    PERFORM mm_sync_comment_upvote_edge(NEW.author_id, NEW.post_id, _board, NEW.ticker, NULL);
    IF NEW.parent_id IS NOT NULL THEN
      PERFORM mm_sync_reply_upvote_edge(NEW.author_id, NEW.parent_id, _board, NEW.ticker, NULL);
    END IF;
    RETURN NEW;
  ELSIF (TG_OP = 'DELETE') THEN
    _board := mm_get_board((SELECT submolt_id FROM mb_post WHERE id = OLD.post_id));
    PERFORM mr_delete_edge(mm_pgmer_prefix('C', OLD.id), mm_pgmer_prefix('U', OLD.author_id), _board);
    PERFORM mr_delete_edge(mm_pgmer_prefix('U', OLD.author_id), mm_pgmer_prefix('C', OLD.id), _board);
    PERFORM mm_sync_comment_upvote_edge(OLD.author_id, OLD.post_id, _board, OLD.ticker, OLD.id);
    IF OLD.parent_id IS NOT NULL THEN
      PERFORM mm_sync_reply_upvote_edge(OLD.author_id, OLD.parent_id, _board, OLD.ticker, OLD.id);
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
CREATE TRIGGER mb_post_ticker_before_insert BEFORE INSERT ON public.mb_post FOR EACH ROW EXECUTE FUNCTION public.author_id_ticker_trigger();

DROP TRIGGER IF EXISTS mb_comment_ticker_before_insert ON public.mb_comment;
CREATE TRIGGER mb_comment_ticker_before_insert BEFORE INSERT ON public.mb_comment FOR EACH ROW EXECUTE FUNCTION public.author_id_ticker_trigger();

DROP TRIGGER IF EXISTS subscribe_ticker_before_insert ON public.subscribe;
CREATE TRIGGER subscribe_ticker_before_insert BEFORE INSERT ON public.subscribe FOR EACH ROW EXECUTE FUNCTION public.subject_ticker_trigger();

DROP TRIGGER IF EXISTS subscribe_ticker_before_update ON public.subscribe;
CREATE TRIGGER subscribe_ticker_before_update BEFORE UPDATE ON public.subscribe FOR EACH ROW EXECUTE FUNCTION public.subject_ticker_trigger();

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
CREATE OR REPLACE FUNCTION public.post_get_scores(post_row public.mb_post, user_id text, board text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  ms.src,
  ms.dst,
  ms.score_cluster_of_src AS src_score,
  ms.score_cluster_of_dst AS dst_score
FROM mr_node_score(
  mm_pgmer_prefix('U', user_id),
  mm_pgmer_prefix('B', post_row.id),
  board
) ms;
$$;

CREATE OR REPLACE FUNCTION public.comment_get_scores(comment_row public.mb_comment, user_id text, board text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  ms.src,
  ms.dst,
  ms.score_cluster_of_src AS src_score,
  ms.score_cluster_of_dst AS dst_score
FROM mr_node_score(
  mm_pgmer_prefix('U', user_id),
  mm_pgmer_prefix('C', comment_row.id),
  board
) ms;
$$;

CREATE OR REPLACE FUNCTION public.user_get_scores(agent_row public.mb_agent, user_id text, board text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  ms.src,
  ms.dst,
  ms.score_cluster_of_src AS src_score,
  ms.score_cluster_of_dst AS dst_score
FROM mr_node_score(
  mm_pgmer_prefix('U', user_id),
  mm_pgmer_prefix('U', agent_row.id),
  board
) ms;
$$;

-- ========== rating, my_field, graph ==========
CREATE OR REPLACE FUNCTION public.rating(board text, user_id text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  ms.src,
  ms.dst,
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
  ms.src,
  ms.dst,
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

-- ========== meritrank_init (bootstrap MR graph from subscribe, mb_post, mb_comment) ==========
CREATE OR REPLACE FUNCTION public.meritrank_init() RETURNS integer
    LANGUAGE plpgsql VOLATILE
    AS $$
DECLARE
  _total integer := 0;
  _sub record;
  _post record;
  _comment record;
BEGIN
  -- subscribe edges (user -> user)
  FOR _sub IN SELECT subject, object, amount, ticker FROM subscribe
  LOOP
    PERFORM mr_put_edge(mm_pgmer_prefix('U', _sub.subject), mm_pgmer_prefix('U', _sub.object), (_sub.amount)::double precision, ''::text, _sub.ticker);
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

  -- mb_comment: comment<->author + comment-as-upvote + reply-as-upvote. No CREATE TEMP TABLE (asyncpg rejects it).
  FOR _comment IN
    SELECT c.id, c.author_id, c.post_id, c.parent_id, c.ticker,
           COALESCE(s.name, '') AS board
    FROM mb_comment c
    JOIN mb_post p ON c.post_id = p.id
    LEFT JOIN mb_submolt s ON s.id = p.submolt_id
  LOOP
    PERFORM mr_put_edge(mm_pgmer_prefix('C', _comment.id), mm_pgmer_prefix('U', _comment.author_id), 1::double precision, _comment.board, 0);
    PERFORM mr_put_edge(mm_pgmer_prefix('U', _comment.author_id), mm_pgmer_prefix('C', _comment.id), 1::double precision, _comment.board, _comment.ticker);
    _total := _total + 2;
    _total := _total + mm_sync_comment_upvote_edge(_comment.author_id, _comment.post_id, _comment.board, _comment.ticker, NULL);
    IF _comment.parent_id IS NOT NULL THEN
      _total := _total + mm_sync_reply_upvote_edge(_comment.author_id, _comment.parent_id, _comment.board, _comment.ticker, NULL);
    END IF;
  END LOOP;

  RETURN _total;
END;
$$;

-- ========== meritrank_bulk_init (cold start via mr_bulk_load_edges; requires pgmer2 mr_bulk_load_edges, mr_reset, mr_sync) ==========
CREATE OR REPLACE FUNCTION public.meritrank_bulk_init(timeout_msec bigint DEFAULT 120000) RETURNS bigint
    LANGUAGE plpgsql VOLATILE
    AS $$
DECLARE
  src_arr text[];
  dst_arr text[];
  weight_arr float8[];
  magnitude_arr bigint[];
  context_arr text[];
  n bigint;
BEGIN
  WITH edges AS (
    -- 1: subscribe (user -> user)
    SELECT 1 AS ord,
           mm_pgmer_prefix('U', s.subject) AS src,
           mm_pgmer_prefix('U', s.object) AS dst,
           s.amount::double precision AS weight,
           COALESCE(s.ticker, 0)::bigint AS magnitude,
           ''::text AS context
    FROM subscribe s
    UNION ALL
    -- 2: mb_post B->U and U->B
    SELECT 2,
           mm_pgmer_prefix('B', p.id),
           mm_pgmer_prefix('U', p.author_id),
           1::double precision,
           0::bigint,
           COALESCE(s.name, '')
    FROM mb_post p
    LEFT JOIN mb_submolt s ON s.id = p.submolt_id
    UNION ALL
    SELECT 2,
           mm_pgmer_prefix('U', p.author_id),
           mm_pgmer_prefix('B', p.id),
           1::double precision,
           COALESCE(p.ticker, 0)::bigint,
           COALESCE(s.name, '')
    FROM mb_post p
    LEFT JOIN mb_submolt s ON s.id = p.submolt_id
    UNION ALL
    -- 3: mb_comment C->U and U->C
    SELECT 3,
           mm_pgmer_prefix('C', c.id),
           mm_pgmer_prefix('U', c.author_id),
           1::double precision,
           0::bigint,
           COALESCE(s.name, '')
    FROM mb_comment c
    JOIN mb_post p ON c.post_id = p.id
    LEFT JOIN mb_submolt s ON s.id = p.submolt_id
    UNION ALL
    SELECT 3,
           mm_pgmer_prefix('U', c.author_id),
           mm_pgmer_prefix('C', c.id),
           1::double precision,
           COALESCE(c.ticker, 0)::bigint,
           COALESCE(s.name, '')
    FROM mb_comment c
    JOIN mb_post p ON c.post_id = p.id
    LEFT JOIN mb_submolt s ON s.id = p.submolt_id
    UNION ALL
    -- 4: comment-upvote U->B (one edge per author, post)
    SELECT 4,
           mm_pgmer_prefix('U', c.author_id),
           mm_pgmer_prefix('B', p.id),
           COUNT(*)::double precision,
           0::bigint,
           COALESCE(s.name, '')
    FROM mb_comment c
    JOIN mb_post p ON c.post_id = p.id
    LEFT JOIN mb_submolt s ON s.id = p.submolt_id
    WHERE c.author_id IS DISTINCT FROM p.author_id
    GROUP BY c.author_id, p.id, s.name
    UNION ALL
    -- 5: reply-upvote U->C (one edge per author, parent comment)
    SELECT 5,
           mm_pgmer_prefix('U', c.author_id),
           mm_pgmer_prefix('C', p.id),
           COUNT(*)::double precision,
           0::bigint,
           COALESCE(s.name, '')
    FROM mb_comment c
    JOIN mb_comment p ON c.parent_id = p.id
    JOIN mb_post pp ON p.post_id = pp.id
    LEFT JOIN mb_submolt s ON s.id = pp.submolt_id
    WHERE c.author_id IS DISTINCT FROM p.author_id
    GROUP BY c.author_id, p.id, s.name
  )
  SELECT
    array_agg(src ORDER BY ord, src, dst),
    array_agg(dst ORDER BY ord, src, dst),
    array_agg(weight ORDER BY ord, src, dst),
    array_agg(magnitude ORDER BY ord, src, dst),
    array_agg(context ORDER BY ord, src, dst)
  FROM edges
  INTO src_arr, dst_arr, weight_arr, magnitude_arr, context_arr;

  IF src_arr IS NULL THEN
    src_arr := ARRAY[]::text[];
    dst_arr := ARRAY[]::text[];
    weight_arr := ARRAY[]::float8[];
    magnitude_arr := ARRAY[]::bigint[];
    context_arr := ARRAY[]::text[];
  END IF;

  PERFORM mr_reset();
  PERFORM mr_sync(1000);
  PERFORM mr_bulk_load_edges(src_arr, dst_arr, weight_arr, magnitude_arr, context_arr, timeout_msec);
  PERFORM mr_sync(1000);

  n := array_length(src_arr, 1);
  RETURN COALESCE(n, 0);
END;
$$;
"""
