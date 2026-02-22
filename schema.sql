--
-- PostgreSQL database dump
--

-- Dumped from database version 17.4
-- Dumped by pg_dump version 17.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgmer2; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgmer2 WITH SCHEMA public;


--
-- Name: EXTENSION pgmer2; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgmer2 IS 'pgmer2:  Created by pgrx';


--
-- Name: post_before_insert(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.post_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  UPDATE user_vsids SET counter = counter + 1
    WHERE user_id = NEW.user_id
    RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: post; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.post (
    id text DEFAULT concat('B', "substring"((gen_random_uuid())::text, '\w{12}'::text)) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    user_id text NOT NULL,
    title text NOT NULL,
    description text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    lat double precision,
    long double precision,
    board text NOT NULL,
    ticker integer DEFAULT 0 NOT NULL,
    start_at timestamp with time zone,
    end_at timestamp with time zone,
    tags text DEFAULT ''::text NOT NULL,
    CONSTRAINT post__description_len CHECK ((char_length(description) <= 2048)),
    CONSTRAINT post__title_len CHECK ((char_length(title) <= 128)),
    CONSTRAINT post_board_name_length CHECK (((char_length(board) >= 3) AND (char_length(board) <= 32)))
);


--
-- Name: post_get_my_vote(public.post, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.post_get_my_vote(post_row public.post, user_id text) RETURNS integer
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


--
-- Name: mutual_score; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.mutual_score AS
 SELECT ''::text AS src,
    ''::text AS dst,
    (0)::double precision AS src_score,
    (0)::double precision AS dst_score
  WHERE false;


--
-- Name: post_get_scores(public.post, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.post_get_scores(post_row public.post, user_id text, board text) RETURNS SETOF public.mutual_score
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


--
-- Name: comment_before_insert(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.comment_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  UPDATE user_vsids SET counter = counter + 1
    WHERE user_id = NEW.user_id
    RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;


--
-- Name: comment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.comment (
    id text DEFAULT concat('C', "substring"((gen_random_uuid())::text, '\w{12}'::text)) NOT NULL,
    user_id text NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    post_id text NOT NULL,
    ticker integer DEFAULT 0 NOT NULL,
    CONSTRAINT comment_content_length CHECK (((char_length(content) > 0) AND (char_length(content) <= 2048)))
);


--
-- Name: comment_get_my_vote(public.comment, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.comment_get_my_vote(comment_row public.comment, user_id text) RETURNS integer
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


--
-- Name: comment_get_scores(public.comment, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.comment_get_scores(comment_row public.comment, user_id text, board text) RETURNS SETOF public.mutual_score
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


--
-- Name: graph(text, text, boolean, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.graph(focus text, board text, positive_only boolean, user_id text) RETURNS SETOF public.mutual_score
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


--
-- Name: meritrank_init(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.meritrank_init() RETURNS integer
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
    -- Post -> Author
    PERFORM mr_put_edge(
      _post.id,
      _post.user_id,
      1,
      _post.board,
      0
    );
    -- Author -> Post
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
    -- Comment -> Author
    PERFORM mr_put_edge(
      _comment.id,
      _comment.user_id,
      1,
      _comment.board,
      0
    );
    -- Author -> Comment
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


--
-- Name: my_field(text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.my_field(board text, user_id text) RETURNS SETOF public.mutual_score
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


--
-- Name: notify_meritrank_post_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.notify_meritrank_post_mutation() RETURNS trigger
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


--
-- Name: notify_meritrank_comment_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.notify_meritrank_comment_mutation() RETURNS trigger
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


--
-- Name: notify_meritrank_vote_post_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.notify_meritrank_vote_post_mutation() RETURNS trigger
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


--
-- Name: notify_meritrank_vote_comment_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.notify_meritrank_vote_comment_mutation() RETURNS trigger
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


--
-- Name: notify_meritrank_vote_user_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.notify_meritrank_vote_user_mutation() RETURNS trigger
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


--
-- Name: on_user_created(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.on_user_created() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO user_vsids VALUES (NEW.id, DEFAULT, DEFAULT);
  RETURN NEW;
END;
$$;


--
-- Name: neighbors_score; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.neighbors_score AS
 SELECT ''::text AS src,
    ''::text AS dst,
    (0)::double precision AS src_score,
    (0)::double precision AS dst_score,
    0 AS src_cluster_score,
    0 AS dst_cluster_score
  WHERE false;


--
-- Name: rating(text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.rating(board text, user_id text) RETURNS SETOF public.mutual_score
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


--
-- Name: set_current_timestamp_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_current_timestamp_updated_at() RETURNS trigger
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


--
-- Name: user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."user" (
    id text DEFAULT concat('U', "substring"((gen_random_uuid())::text, '\w{12}'::text)) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    title text DEFAULT ''::text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    public_key text NOT NULL,
    privileges jsonb,
    CONSTRAINT user__description_len CHECK ((char_length(description) <= 2048)),
    CONSTRAINT user__title_len CHECK ((char_length(title) <= 128))
);


--
-- Name: user_get_my_vote(public."user", text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.user_get_my_vote(user_row public."user", user_id text) RETURNS integer
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


--
-- Name: user_get_scores(public."user", text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.user_get_scores(user_row public."user", user_id text, board text) RETURNS SETOF public.mutual_score
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


--
-- Name: vote_post_before_insert(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.vote_post_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  UPDATE user_vsids SET counter = counter + 1
    WHERE user_id = NEW.subject
    RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;


--
-- Name: vote_comment_before_insert(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.vote_comment_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  UPDATE user_vsids SET counter = counter + 1
    WHERE user_id = NEW.subject
    RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;


--
-- Name: vote_user_before_insert(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.vote_user_before_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  UPDATE user_vsids SET counter = counter + 1
    WHERE user_id = NEW.subject
    RETURNING counter INTO NEW.ticker;
  RETURN NEW;
END;
$$;


--
-- Name: edge; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.edge AS
 SELECT ''::text AS src,
    ''::text AS dst,
    (0)::double precision AS score
  WHERE false;


--
-- Name: schema_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_version (
    version text NOT NULL COLLATE pg_catalog."C",
    applied_at timestamp without time zone NOT NULL
);


--
-- Name: user_board; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_board (
    user_id text NOT NULL,
    board_name text NOT NULL,
    CONSTRAINT user_board_name_length CHECK (((char_length(board_name) >= 3) AND (char_length(board_name) <= 32)))
);


--
-- Name: user_vsids; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_vsids (
    user_id text NOT NULL,
    counter integer DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: vote_post; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vote_post (
    subject text NOT NULL,
    object text NOT NULL,
    amount integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    ticker integer DEFAULT 0 NOT NULL
);


--
-- Name: vote_comment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vote_comment (
    subject text NOT NULL,
    object text NOT NULL,
    amount integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    ticker integer DEFAULT 0 NOT NULL
);


--
-- Name: vote_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vote_user (
    subject text NOT NULL,
    object text NOT NULL,
    amount integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    ticker integer DEFAULT 0 NOT NULL,
    CONSTRAINT vote_user__amount CHECK (((amount >= '-1'::integer) AND (amount <= 1)))
);


--
-- Name: post post_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.post
    ADD CONSTRAINT post_pkey PRIMARY KEY (id);


--
-- Name: comment comment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment
    ADD CONSTRAINT comment_pkey PRIMARY KEY (id);


--
-- Name: schema_version schema_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_version
    ADD CONSTRAINT schema_version_pkey PRIMARY KEY (version);


--
-- Name: user_board user_board_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_board
    ADD CONSTRAINT user_board_pkey PRIMARY KEY (user_id, board_name);


--
-- Name: user user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."user"
    ADD CONSTRAINT user_pkey PRIMARY KEY (id);


--
-- Name: user user_public_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."user"
    ADD CONSTRAINT user_public_key_key UNIQUE (public_key);


--
-- Name: user_vsids user_vsids_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_vsids
    ADD CONSTRAINT user_vsids_pkey PRIMARY KEY (user_id);


--
-- Name: vote_post vote_post_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vote_post
    ADD CONSTRAINT vote_post_pkey PRIMARY KEY (subject, object);


--
-- Name: vote_comment vote_comment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vote_comment
    ADD CONSTRAINT vote_comment_pkey PRIMARY KEY (subject, object);


--
-- Name: vote_user vote_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vote_user
    ADD CONSTRAINT vote_user_pkey PRIMARY KEY (subject, object);


--
-- Name: post_author_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX post_author_id ON public.post USING btree (user_id);


--
-- Name: post notify_meritrank_post_mutation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER notify_meritrank_post_mutation AFTER INSERT OR DELETE ON public.post FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_post_mutation();


--
-- Name: comment notify_meritrank_comment_mutation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER notify_meritrank_comment_mutation AFTER INSERT OR DELETE ON public.comment FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_comment_mutation();


--
-- Name: vote_post notify_meritrank_vote_post_mutation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER notify_meritrank_vote_post_mutation AFTER INSERT OR UPDATE ON public.vote_post FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_vote_post_mutation();


--
-- Name: vote_comment notify_meritrank_vote_comment_mutation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER notify_meritrank_vote_comment_mutation AFTER INSERT OR UPDATE ON public.vote_comment FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_vote_comment_mutation();


--
-- Name: vote_user notify_meritrank_vote_user_mutation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER notify_meritrank_vote_user_mutation AFTER INSERT OR UPDATE ON public.vote_user FOR EACH ROW EXECUTE FUNCTION public.notify_meritrank_vote_user_mutation();


--
-- Name: user on_user_created; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER on_user_created AFTER INSERT ON public."user" FOR EACH ROW EXECUTE FUNCTION public.on_user_created();


--
-- Name: post public_post_before_insert; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER public_post_before_insert BEFORE INSERT ON public.post FOR EACH ROW EXECUTE FUNCTION public.post_before_insert();


--
-- Name: comment public_comment_before_insert; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER public_comment_before_insert BEFORE INSERT ON public.comment FOR EACH ROW EXECUTE FUNCTION public.comment_before_insert();


--
-- Name: vote_post public_vote_post_before_insert; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER public_vote_post_before_insert BEFORE INSERT ON public.vote_post FOR EACH ROW EXECUTE FUNCTION public.vote_post_before_insert();


--
-- Name: vote_comment public_vote_comment_before_insert; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER public_vote_comment_before_insert BEFORE INSERT ON public.vote_comment FOR EACH ROW EXECUTE FUNCTION public.vote_comment_before_insert();


--
-- Name: vote_user public_vote_user_before_insert; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER public_vote_user_before_insert BEFORE INSERT ON public.vote_user FOR EACH ROW EXECUTE FUNCTION public.vote_user_before_insert();


--
-- Name: post set_public_post_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER set_public_post_updated_at BEFORE UPDATE ON public.post FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();


--
-- Name: TRIGGER set_public_post_updated_at ON post; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TRIGGER set_public_post_updated_at ON public.post IS 'trigger to set value of column "updated_at" to current timestamp on row update';


--
-- Name: user set_public_user_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER set_public_user_updated_at BEFORE UPDATE ON public."user" FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();


--
-- Name: user_vsids set_public_user_vsids_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER set_public_user_vsids_updated_at BEFORE UPDATE ON public.user_vsids FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();


--
-- Name: TRIGGER set_public_user_vsids_updated_at ON user_vsids; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TRIGGER set_public_user_vsids_updated_at ON public.user_vsids IS 'trigger to set value of column "updated_at" to current timestamp on row update';


--
-- Name: vote_post set_public_vote_post_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER set_public_vote_post_updated_at BEFORE UPDATE ON public.vote_post FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();


--
-- Name: TRIGGER set_public_vote_post_updated_at ON vote_post; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TRIGGER set_public_vote_post_updated_at ON public.vote_post IS 'trigger to set value of column "updated_at" to current timestamp on row update';


--
-- Name: vote_comment set_public_vote_comment_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER set_public_vote_comment_updated_at BEFORE UPDATE ON public.vote_comment FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();


--
-- Name: TRIGGER set_public_vote_comment_updated_at ON vote_comment; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TRIGGER set_public_vote_comment_updated_at ON public.vote_comment IS 'trigger to set value of column "updated_at" to current timestamp on row update';


--
-- Name: vote_user set_public_vote_user_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER set_public_vote_user_updated_at BEFORE UPDATE ON public.vote_user FOR EACH ROW EXECUTE FUNCTION public.set_current_timestamp_updated_at();


--
-- Name: TRIGGER set_public_vote_user_updated_at ON vote_user; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TRIGGER set_public_vote_user_updated_at ON public.vote_user IS 'trigger to set value of column "updated_at" to current timestamp on row update';


--
-- Name: post post_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.post
    ADD CONSTRAINT post_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: comment comment_post_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment
    ADD CONSTRAINT comment_post_id_fkey FOREIGN KEY (post_id) REFERENCES public.post(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: comment comment_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment
    ADD CONSTRAINT comment_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: user_board user_board_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_board
    ADD CONSTRAINT user_board_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id) ON UPDATE RESTRICT ON DELETE CASCADE;


--
-- Name: user_vsids user_vsids_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_vsids
    ADD CONSTRAINT user_vsids_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id) ON UPDATE RESTRICT ON DELETE CASCADE;


--
-- Name: vote_post vote_post_object_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vote_post
    ADD CONSTRAINT vote_post_object_fkey FOREIGN KEY (object) REFERENCES public.post(id) ON UPDATE RESTRICT ON DELETE CASCADE;


--
-- Name: vote_post vote_post_subject_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vote_post
    ADD CONSTRAINT vote_post_subject_fkey FOREIGN KEY (subject) REFERENCES public."user"(id) ON UPDATE RESTRICT ON DELETE CASCADE;


--
-- Name: vote_comment vote_comment_object_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vote_comment
    ADD CONSTRAINT vote_comment_object_fkey FOREIGN KEY (object) REFERENCES public.comment(id) ON UPDATE RESTRICT ON DELETE CASCADE;


--
-- Name: vote_comment vote_comment_subject_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vote_comment
    ADD CONSTRAINT vote_comment_subject_fkey FOREIGN KEY (subject) REFERENCES public."user"(id) ON UPDATE RESTRICT ON DELETE CASCADE;


--
-- Name: vote_user vote_user_object_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vote_user
    ADD CONSTRAINT vote_user_object_fkey FOREIGN KEY (object) REFERENCES public."user"(id) ON UPDATE RESTRICT ON DELETE CASCADE;


--
-- Name: vote_user vote_user_subject_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vote_user
    ADD CONSTRAINT vote_user_subject_fkey FOREIGN KEY (subject) REFERENCES public."user"(id) ON UPDATE RESTRICT ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

