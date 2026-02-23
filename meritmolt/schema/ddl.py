"""SQL DDL constants for MeritMolt schema: extension, views, trigger functions, triggers,
wrapper functions.

All use CREATE OR REPLACE / CREATE ... IF NOT EXISTS / DROP IF EXISTS
for idempotent application at startup.
"""

# ruff: noqa: E501

EXTENSION_SQL = """
CREATE EXTENSION IF NOT EXISTS pgmer2 WITH SCHEMA public;
"""

# Type-definition views (return type for MR wrapper functions)
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

# Trigger functions (call mr_put_edge / mr_delete_edge or maintain ticker / updated_at)
TRIGGER_FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION public.set_current_timestamp_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  _new record;
BEGIN
  _new := NEW;
  _new."updated_at" = NOW();
  RETURN _new;
END;
$$;

CREATE OR REPLACE FUNCTION public.on_user_created() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO user_vsids VALUES (NEW.id, DEFAULT, DEFAULT);
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.post_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  UPDATE user_vsids SET counter = counter + 1
    WHERE user_id = NEW.user_id
    RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.comment_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  UPDATE user_vsids SET counter = counter + 1
    WHERE user_id = NEW.user_id
    RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.vote_user_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  UPDATE user_vsids SET counter = counter + 1
    WHERE user_id = NEW.subject
    RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.vote_post_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  UPDATE user_vsids SET counter = counter + 1
    WHERE user_id = NEW.subject
    RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.vote_comment_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  UPDATE user_vsids SET counter = counter + 1
    WHERE user_id = NEW.subject
    RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.notify_meritrank_post_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF (TG_OP = 'INSERT') THEN
    PERFORM mr_put_edge(
      NEW.id,
      NEW.user_id,
      1::double precision,
      NEW.board,
      0
    );
    PERFORM mr_put_edge(
      NEW.user_id,
      NEW.id,
      1::double precision,
      NEW.board,
      NEW.ticker
    );
    RETURN NEW;

  ELSIF (TG_OP = 'DELETE') THEN
    PERFORM mr_delete_edge(OLD.id, OLD.user_id, OLD.board);
    PERFORM mr_delete_edge(OLD.user_id, OLD.id, OLD.board);
    RETURN OLD;
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.notify_meritrank_comment_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  board text;
BEGIN
  SELECT post.board
    INTO board
    FROM post
    WHERE post.id = NEW.post_id;

  IF (TG_OP = 'INSERT') THEN
    PERFORM mr_put_edge(
      NEW.id,
      NEW.user_id,
      1::double precision,
      board,
      0
    );
    PERFORM mr_put_edge(
      NEW.user_id,
      NEW.id,
      1::double precision,
      board,
      NEW.ticker
    );
    RETURN NEW;

  ELSIF (TG_OP = 'DELETE') THEN
    PERFORM mr_delete_edge(OLD.id, OLD.user_id, board);
    PERFORM mr_delete_edge(OLD.user_id, OLD.id, board);
    RETURN OLD;
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.notify_meritrank_vote_user_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
    PERFORM mr_put_edge(
      NEW.subject,
      NEW.object,
      (NEW.amount)::double precision,
      ''::text, NEW.ticker
    );
    RETURN NEW;

  ELSIF (TG_OP = 'DELETE') THEN
    PERFORM mr_delete_edge(
      OLD.subject,
      OLD.object,
      ''::text
    );
    RETURN OLD;
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.notify_meritrank_vote_post_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  _board text;
BEGIN
  SELECT post.board
    INTO STRICT _board
    FROM post
    WHERE post.id = NEW.object;

  IF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
    PERFORM mr_put_edge(
      NEW.subject,
      NEW.object,
      (NEW.amount)::double precision,
      _board,
      NEW.ticker
    );
    RETURN NEW;

  ELSIF (TG_OP = 'DELETE') THEN
    PERFORM mr_delete_edge(
      OLD.subject,
      OLD.object,
      _board
    );
    RETURN OLD;
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.notify_meritrank_vote_comment_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  _board text;
  post_id text;
BEGIN
  SELECT comment.post_id
    INTO post_id
    FROM comment
    WHERE comment.id = NEW.object;

  SELECT post.board
    INTO _board
    FROM post
    WHERE post.id = post_id;

  IF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
    PERFORM mr_put_edge(
      NEW.subject,
      NEW.object,
      (NEW.amount)::double precision,
      _board,
      NEW.ticker
    );
    RETURN NEW;

  ELSIF (TG_OP = 'DELETE') THEN
    PERFORM mr_delete_edge(
      OLD.subject,
      OLD.object,
      _board
    );
    RETURN OLD;
  END IF;
END;
$$;
"""

# Triggers: drop if exists then create (idempotent; PG < 14 has no OR REPLACE)
TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS notify_meritrank_post_mutation ON public.post;
CREATE TRIGGER notify_meritrank_post_mutation AFTER INSERT OR DELETE ON public.post FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_post_mutation();

DROP TRIGGER IF EXISTS notify_meritrank_comment_mutation ON public.comment;
CREATE TRIGGER notify_meritrank_comment_mutation AFTER INSERT OR DELETE ON public.comment FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_comment_mutation();

DROP TRIGGER IF EXISTS notify_meritrank_vote_post_mutation ON public.vote_post;
CREATE TRIGGER notify_meritrank_vote_post_mutation AFTER INSERT OR UPDATE ON public.vote_post FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_vote_post_mutation();

DROP TRIGGER IF EXISTS notify_meritrank_vote_comment_mutation ON public.vote_comment;
CREATE TRIGGER notify_meritrank_vote_comment_mutation AFTER INSERT OR UPDATE ON public.vote_comment FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_vote_comment_mutation();

DROP TRIGGER IF EXISTS notify_meritrank_vote_user_mutation ON public.vote_user;
CREATE TRIGGER notify_meritrank_vote_user_mutation AFTER INSERT OR UPDATE OR DELETE ON public.vote_user FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_vote_user_mutation();

DROP TRIGGER IF EXISTS on_user_created ON public."user";
CREATE TRIGGER on_user_created AFTER INSERT ON public."user" FOR EACH ROW EXECUTE FUNCTION public.on_user_created();

DROP TRIGGER IF EXISTS public_post_before_insert ON public.post;
CREATE TRIGGER public_post_before_insert BEFORE INSERT ON public.post FOR EACH ROW EXECUTE FUNCTION public.post_before_insert();

DROP TRIGGER IF EXISTS public_comment_before_insert ON public.comment;
CREATE TRIGGER public_comment_before_insert BEFORE INSERT ON public.comment FOR EACH ROW EXECUTE FUNCTION public.comment_before_insert();

DROP TRIGGER IF EXISTS public_vote_post_before_insert ON public.vote_post;
CREATE TRIGGER public_vote_post_before_insert BEFORE INSERT ON public.vote_post FOR EACH ROW EXECUTE FUNCTION public.vote_post_before_insert();

DROP TRIGGER IF EXISTS public_vote_comment_before_insert ON public.vote_comment;
CREATE TRIGGER public_vote_comment_before_insert BEFORE INSERT ON public.vote_comment FOR EACH ROW EXECUTE FUNCTION public.vote_comment_before_insert();

DROP TRIGGER IF EXISTS public_vote_user_before_insert ON public.vote_user;
CREATE TRIGGER public_vote_user_before_insert BEFORE INSERT ON public.vote_user FOR EACH ROW EXECUTE FUNCTION public.vote_user_before_insert();

DROP TRIGGER IF EXISTS set_public_post_updated_at ON public.post;
CREATE TRIGGER set_public_post_updated_at BEFORE UPDATE ON public.post FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS set_public_user_updated_at ON public."user";
CREATE TRIGGER set_public_user_updated_at BEFORE UPDATE ON public."user" FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS set_public_user_vsids_updated_at ON public.user_vsids;
CREATE TRIGGER set_public_user_vsids_updated_at BEFORE UPDATE ON public.user_vsids FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS set_public_vote_post_updated_at ON public.vote_post;
CREATE TRIGGER set_public_vote_post_updated_at BEFORE UPDATE ON public.vote_post FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS set_public_vote_comment_updated_at ON public.vote_comment;
CREATE TRIGGER set_public_vote_comment_updated_at BEFORE UPDATE ON public.vote_comment FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();

DROP TRIGGER IF EXISTS set_public_vote_user_updated_at ON public.vote_user;
CREATE TRIGGER set_public_vote_user_updated_at BEFORE UPDATE ON public.vote_user FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();
"""

# Wrapper functions that call MR extension (mr_node_score, mr_mutual_scores, mr_scores, mr_graph)
WRAPPER_FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION public.user_get_my_vote(user_row public."user", user_id text) RETURNS integer
    LANGUAGE sql STABLE
    AS $$
SELECT COALESCE(
  (SELECT amount FROM vote_user
    WHERE subject = user_id
      AND object = user_row.id
  ),
  0
);
$$;

CREATE OR REPLACE FUNCTION public.user_get_scores(user_row public."user", user_id text, board text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  src,
  dst,
  score_cluster_of_src AS src_score,
  score_cluster_of_dst AS dst_score
FROM mr_node_score(
  user_id,
  user_row.id,
  board
);
$$;

CREATE OR REPLACE FUNCTION public.post_get_my_vote(post_row public.post, user_id text) RETURNS integer
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT COALESCE(
  (SELECT amount FROM vote_post WHERE
    subject = user_id
    AND object = post_row.id
  ),
  0
);
$$;

CREATE OR REPLACE FUNCTION public.post_get_scores(post_row public.post, user_id text, board text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  src,
  dst,
  score_cluster_of_src AS src_score,
  score_cluster_of_dst AS dst_score
FROM mr_node_score(
  user_id,
  post_row.id,
  board
);
$$;

CREATE OR REPLACE FUNCTION public.comment_get_my_vote(comment_row public.comment, user_id text) RETURNS integer
    LANGUAGE sql STABLE
    AS $$
SELECT COALESCE(
  (SELECT amount FROM vote_comment WHERE
    subject = user_id
    AND object = comment_row.id
  ),
  0
);
$$;

CREATE OR REPLACE FUNCTION public.comment_get_scores(comment_row public.comment, user_id text, board text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  src,
  dst,
  score_cluster_of_src AS src_score,
  score_cluster_of_dst AS dst_score
FROM mr_node_score(
  user_id,
  comment_row.id,
  board
);
$$;

CREATE OR REPLACE FUNCTION public.rating(board text, user_id text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  src,
  dst,
  score_cluster_of_src AS src_score,
  score_cluster_of_dst AS dst_score
FROM mr_mutual_scores(
  user_id,
  board
);
$$;

CREATE OR REPLACE FUNCTION public.my_field(board text, user_id text) RETURNS SETOF public.mutual_score
    LANGUAGE sql IMMUTABLE
    AS $$
SELECT
  src,
  dst,
  score_cluster_of_src AS src_score,
  score_cluster_of_dst AS dst_score
FROM
  mr_scores(
    user_id,
    true,
    board,
    'B',
    null,
    null,
    '0',
    null,
    0,
    100
  );
$$;

CREATE OR REPLACE FUNCTION public.graph(focus text, board text, positive_only boolean, user_id text) RETURNS SETOF public.mutual_score
    LANGUAGE sql STABLE
    AS $$
SELECT
  src,
  dst,
  score_cluster_of_ego AS src_score,
  score_cluster_of_dst AS dst_score
FROM
  mr_graph(
    user_id,
    focus,
    board,
    positive_only,
    0,
    100
  );
$$;

CREATE OR REPLACE FUNCTION public.meritrank_init() RETURNS integer
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
  _count integer := 0;
  _total integer := 0;
  _post record;
  _comment record;
BEGIN
  -- Edges User -> User (vote)
  SELECT count(*) INTO STRICT _count FROM (
    SELECT mr_put_edge(
      edge.src,
      edge.dst,
      edge.amount,
      '',
      edge.ticker
    ) FROM (
      SELECT vote_user.subject AS src,
        vote_user.object AS dst,
        vote_user.amount AS amount,
        vote_user.ticker
      FROM vote_user
    ) AS edge);
  _total := _total + _count;

  -- Edges Author <-> Post
  FOR _post IN
    SELECT id, user_id, board, ticker
      FROM "post"
  LOOP
    PERFORM mr_put_edge(
      _post.id,
      _post.user_id,
      1,
      _post.board,
      0
    );
    PERFORM mr_put_edge(
      _post.user_id,
      _post.id,
      1,
      _post.board,
      _post.ticker
    );
    _total := _total + 2;
  END LOOP;

  -- Edges User -> Post (vote)
  SELECT count(*) INTO STRICT _count FROM (
    SELECT mr_put_edge(
      edge.src,
      edge.dst,
      edge.amount,
      edge.board,
      edge.ticker
    ) FROM (
      SELECT vote_post.subject AS src,
        vote_post.object AS dst,
        vote_post.amount AS amount,
        post.board AS board,
        vote_post.ticker
      FROM vote_post
        JOIN post ON post.id = vote_post.object
    ) AS edge);
  _total := _total + _count;

  -- Edges Author <-> Comment
  FOR _comment IN
    SELECT "comment".id, "comment".user_id, post.board, "comment".ticker
      FROM "comment"
        JOIN "post" ON "comment".post_id = "post".id
  LOOP
    PERFORM mr_put_edge(
      _comment.id,
      _comment.user_id,
      1,
      _comment.board,
      0
    );
    PERFORM mr_put_edge(
      _comment.user_id,
      _comment.id,
      1,
      _comment.board,
      _comment.ticker
    );
    _total := _total + 2;
  END LOOP;

  -- Edges User -> Comment (vote)
  SELECT count(*) INTO STRICT _count FROM (
    SELECT mr_put_edge(
      edge.src,
      edge.dst,
      edge.amount,
      edge.board,
      edge.ticker
    ) FROM (
      SELECT vote_comment.subject AS src,
        vote_comment.object AS dst,
        vote_comment.amount AS amount,
        post.board AS board,
        vote_comment.ticker
      FROM vote_comment
        JOIN "comment" ON "comment".id = vote_comment.object
        JOIN post ON post.id = "comment".post_id
    ) AS edge);
  _total := _total + _count;

  RETURN _total;
END;
$$;
"""
