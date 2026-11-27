CREATE SCHEMA capri_research_loop;
REVOKE ALL ON SCHEMA capri_research_loop FROM PUBLIC, anon, authenticated, service_role;
CREATE TABLE capri_research_loop.control (
 id boolean PRIMARY KEY DEFAULT true CHECK (id), enabled boolean NOT NULL DEFAULT false,
 daily_limit integer NOT NULL DEFAULT 24 CHECK (daily_limit BETWEEN 1 AND 24),
 minimum_interval interval NOT NULL DEFAULT interval '1 hour' CHECK (minimum_interval >= interval '1 hour'),
 request_day date NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')::date,
 requests_today integer NOT NULL DEFAULT 0 CHECK (requests_today BETWEEN 0 AND 24),
 last_dispatch timestamptz, last_tick timestamptz,
 consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
 stop_reason text NOT NULL DEFAULT 'not_started' CHECK (length(stop_reason) <= 100)
);
INSERT INTO capri_research_loop.control DEFAULT VALUES;
CREATE TABLE capri_research_loop.sources (
 id smallint PRIMARY KEY CHECK (id BETWEEN 1 AND 16),
 repository text NOT NULL UNIQUE CHECK (repository ~ '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' AND length(repository) <= 100),
 branch text NOT NULL CHECK (branch IN ('main','master','develop')),
 readme_path text NOT NULL CHECK (readme_path IN ('README.md','README.rst')),
 enabled boolean NOT NULL DEFAULT true,
 desired_sha text CHECK (desired_sha ~ '^[0-9a-f]{40}$'), latest_sha text CHECK (latest_sha ~ '^[0-9a-f]{40}$'),
 latest_body_sha256 text CHECK (latest_body_sha256 ~ '^[0-9a-f]{64}$'),
 latest_excerpt text CHECK (octet_length(latest_excerpt) <= 16000), latest_body_bytes integer,
 latest_observed_at timestamptz, last_checked_at timestamptz,
 next_due timestamptz NOT NULL DEFAULT now(), failures integer NOT NULL DEFAULT 0 CHECK (failures >= 0)
);
CREATE TABLE capri_research_loop.requests (
 id bigint PRIMARY KEY, source_id smallint NOT NULL REFERENCES capri_research_loop.sources(id),
 kind text NOT NULL CHECK (kind IN ('ref','readme')), pinned_sha text CHECK (pinned_sha ~ '^[0-9a-f]{40}$'),
 url text NOT NULL CHECK (length(url) <= 300), requested_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','collected','unchanged','failed')),
 http_status integer, error_code text CHECK (length(error_code) <= 60), body_bytes integer,
 body_sha256 text CHECK (body_sha256 ~ '^[0-9a-f]{64}$'), changed boolean
);
CREATE UNIQUE INDEX capri_research_one_pending ON capri_research_loop.requests ((true)) WHERE status='pending';
ALTER TABLE capri_research_loop.control ENABLE ROW LEVEL SECURITY;
ALTER TABLE capri_research_loop.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE capri_research_loop.requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA capri_research_loop FROM PUBLIC, anon, authenticated, service_role;
CREATE FUNCTION capri_research_loop.accept_response(p_id bigint, p_status integer, p_body text, p_transport_error boolean DEFAULT false)
RETURNS text LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $$
DECLARE
 r capri_research_loop.requests%ROWTYPE; s capri_research_loop.sources%ROWTYPE;
 sha text; code text; changed_body boolean; n integer;
BEGIN
 SELECT * INTO r FROM capri_research_loop.requests WHERE id=p_id FOR UPDATE;
 IF NOT FOUND OR r.status <> 'pending' THEN RETURN 'ignored'; END IF;
 SELECT * INTO STRICT s FROM capri_research_loop.sources WHERE id=r.source_id FOR UPDATE;
 n := octet_length(p_body);
 IF p_transport_error THEN code := 'transport_or_timeout';
 ELSIF p_status IS DISTINCT FROM 200 THEN code := 'http_not_200';
 ELSIF p_body IS NULL OR n=0 THEN code := 'empty_body';
 ELSIF n > 131072 THEN code := 'body_over_128k';
 ELSIF r.kind='ref' THEN
   BEGIN
     sha := p_body::jsonb #>> '{object,sha}';
     IF sha IS NULL OR sha !~ '^[0-9a-f]{40}$' OR (p_body::jsonb #>> '{object,type}') IS DISTINCT FROM 'commit' THEN code := 'invalid_commit_ref'; END IF;
   EXCEPTION WHEN invalid_text_representation THEN code := 'invalid_ref_json'; END;
 END IF;
 IF code IS NOT NULL THEN
   UPDATE capri_research_loop.requests SET status='failed',completed_at=clock_timestamp(),http_status=p_status,error_code=code,body_bytes=n WHERE id=p_id;
   UPDATE capri_research_loop.sources SET failures=failures+1,enabled=(failures+1 < 3),desired_sha=NULL,next_due=now()+interval '6 hours' WHERE id=s.id;
   UPDATE capri_research_loop.control SET consecutive_failures=consecutive_failures+1,enabled=enabled AND consecutive_failures+1 < 5,
     stop_reason=CASE WHEN consecutive_failures+1 >= 5 THEN 'failure_circuit_open' ELSE stop_reason END WHERE id;
   RETURN 'failed';
 END IF;
 IF r.kind='ref' THEN
   UPDATE capri_research_loop.sources SET last_checked_at=clock_timestamp(),failures=0,
     desired_sha=CASE WHEN latest_sha IS DISTINCT FROM sha THEN sha ELSE NULL END,next_due=now()+interval '24 hours' WHERE id=s.id;
   UPDATE capri_research_loop.requests SET status=CASE WHEN s.latest_sha=sha THEN 'unchanged' ELSE 'collected' END,
     completed_at=clock_timestamp(),http_status=p_status,body_bytes=n,changed=(s.latest_sha IS DISTINCT FROM sha) WHERE id=p_id;
 ELSE
   sha := encode(extensions.digest(convert_to(p_body,'UTF8'),'sha256'),'hex');
   changed_body := s.latest_body_sha256 IS DISTINCT FROM sha;
   UPDATE capri_research_loop.sources SET latest_sha=r.pinned_sha,latest_body_sha256=sha,latest_excerpt=left(p_body,4000),latest_body_bytes=n,
     latest_observed_at=clock_timestamp(),desired_sha=NULL,failures=0,next_due=now()+interval '24 hours' WHERE id=s.id;
   UPDATE capri_research_loop.requests SET status=CASE WHEN changed_body THEN 'collected' ELSE 'unchanged' END,
     completed_at=clock_timestamp(),http_status=p_status,body_bytes=n,body_sha256=sha,changed=changed_body WHERE id=p_id;
 END IF;
 UPDATE capri_research_loop.control SET consecutive_failures=0 WHERE id;
 RETURN 'accepted';
END;
$$;
CREATE FUNCTION capri_research_loop.tick(p_dispatch boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
DECLARE
 c capri_research_loop.control%ROWTYPE; s capri_research_loop.sources%ROWTYPE; r capri_research_loop.requests%ROWTYPE;
 response record; u text; k text; request_id bigint; result text := 'none';
BEGIN
 IF NOT pg_try_advisory_xact_lock(hashtextextended('capri-public-research-loop-v1',0)) THEN RETURN jsonb_build_object('status','busy'); END IF;
 SELECT * INTO STRICT c FROM capri_research_loop.control WHERE id FOR UPDATE;
 IF NOT c.enabled THEN RETURN jsonb_build_object('status','stopped','reason',c.stop_reason); END IF;
 UPDATE capri_research_loop.control SET last_tick=clock_timestamp() WHERE id;
 SELECT * INTO r FROM capri_research_loop.requests WHERE status='pending' FOR UPDATE;
 IF FOUND THEN
   SELECT status_code,content,coalesce(timed_out,false) OR error_msg IS NOT NULL AS transport_error INTO response FROM net._http_response WHERE id=r.id;
   IF FOUND THEN result := capri_research_loop.accept_response(r.id,response.status_code,response.content,response.transport_error);
   ELSIF r.requested_at < now()-interval '10 minutes' THEN result := capri_research_loop.accept_response(r.id,NULL,NULL,true);
   ELSE RETURN jsonb_build_object('status','waiting','request_id',r.id); END IF;
 END IF;
 DELETE FROM cron.job_run_details WHERE jobid=(SELECT jobid FROM cron.job WHERE jobname='capri_public_source_collector') AND runid IN (
   SELECT runid FROM cron.job_run_details WHERE jobid=(SELECT jobid FROM cron.job WHERE jobname='capri_public_source_collector') ORDER BY runid DESC OFFSET 127
 );
 DELETE FROM capri_research_loop.requests WHERE status <> 'pending' AND id IN (
   SELECT id FROM capri_research_loop.requests WHERE status <> 'pending' ORDER BY requested_at DESC,id DESC OFFSET 127
 );
 SELECT * INTO STRICT c FROM capri_research_loop.control WHERE id;
 IF NOT c.enabled THEN RETURN jsonb_build_object('status','stopped','reason',c.stop_reason); END IF;
 IF NOT p_dispatch THEN RETURN jsonb_build_object('status','collected_only','result',result); END IF;
 IF c.request_day <> (now() AT TIME ZONE 'UTC')::date THEN
   UPDATE capri_research_loop.control SET request_day=(now() AT TIME ZONE 'UTC')::date,requests_today=0 WHERE id; c.requests_today := 0;
 END IF;
 IF c.requests_today >= c.daily_limit THEN RETURN jsonb_build_object('status','daily_limit'); END IF;
 IF c.last_dispatch IS NOT NULL AND now()-c.last_dispatch < c.minimum_interval THEN RETURN jsonb_build_object('status','interval_limit','result',result); END IF;
 SELECT * INTO s FROM capri_research_loop.sources WHERE enabled AND (desired_sha IS NOT NULL OR next_due <= now())
   ORDER BY (desired_sha IS NOT NULL) DESC,next_due,id LIMIT 1 FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('status','idle'); END IF;
 IF s.desired_sha IS NOT NULL THEN
   k := 'readme'; u := 'https://raw.githubusercontent.com/' || s.repository || '/' || s.desired_sha || '/' || s.readme_path;
 ELSE k := 'ref'; u := 'https://api.github.com/repos/' || s.repository || '/git/ref/heads/' || s.branch; END IF;
 request_id := net.http_get(url:=u,headers:=jsonb_build_object('User-Agent','Capri-Public-Source-Collector/1.0','Accept','application/vnd.github+json'),timeout_milliseconds:=5000);
 INSERT INTO capri_research_loop.requests(id,source_id,kind,pinned_sha,url) VALUES(request_id,s.id,k,CASE WHEN k='readme' THEN s.desired_sha END,u);
 UPDATE capri_research_loop.control SET last_dispatch=now(),requests_today=requests_today+1 WHERE id;
 RETURN jsonb_build_object('status','dispatched','request_id',request_id,'source_id',s.id,'kind',k,'url',u);
END;
$$;
CREATE FUNCTION capri_research_loop.stop() RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
 UPDATE capri_research_loop.control SET enabled=false,stop_reason='user_stop' WHERE id;
 PERFORM cron.alter_job(jobid,active:=false) FROM cron.job WHERE jobname='capri_public_source_collector';
 RETURN true;
END;
$$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA capri_research_loop FROM PUBLIC, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA capri_research_loop REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
INSERT INTO capri_research_loop.sources(id,repository,branch,readme_path,desired_sha) VALUES
 (1,'encode/httpx','master','README.md','e347fb5e93b91f7cf63a575f595f33db8d90fe20'),
 (2,'agronholm/anyio','master','README.rst','c81f3462c9f60959d8c8a0a00cf3693541d87fcb'),
 (3,'python-jsonschema/jsonschema','main','README.rst','64b62de5df4ec52d7679c770427329e86a22c395'),
 (4,'authlib/authlib','main','README.md','c451e6d1238678231ee21e31964cc8ce34474a37'),
 (5,'pypa/pip-audit','main','README.md','864264baeb9a9e30115a0f2838fe4769cf5a0840'),
 (6,'aquasecurity/trivy','main','README.md','e7c7720564f96b2c53b9837c95f6431f3a5690a1'),
 (7,'gitleaks/gitleaks','master','README.md','5f6ec56cfa6f8c67648d863582c7ae2f206d5c1c'),
 (8,'semgrep/semgrep','develop','README.md','c4dbe9ee2fc6d0022ba02ef6b97c5954ed9549e3'),
 (9,'microsoft/playwright','main','README.md','a804c193562095b0da20e5d4679fa87e4c8e5563'),
 (10,'adbar/trafilatura','master','README.md','f2345ea79039820140c667c5e842856544f9b011'),
 (11,'docling-project/docling','main','README.md','40e490c8d93ef51e4f270feb02c3bb14851f0405'),
 (12,'microsoft/markitdown','main','README.md','ed178952a6672abdfd35b5f9e76a80b6cefc086e'),
 (13,'duckdb/duckdb','main','README.md','07c9a117d026eb4dda7093fa4db0c54d2162cdeb'),
 (14,'pola-rs/polars','main','README.md','4ba28fb5c5d911fdf8a42b40d842158b19456347'),
 (15,'BurntSushi/ripgrep','master','README.md','3e85c6c148fdce38a99ceeb9d2780dc7b03b4a4f'),
 (16,'astral-sh/uv','main','README.md','9bf01bef71c76643290ca17635970076fab1bd0d');
SELECT cron.schedule('capri_public_source_collector','17 * * * *','SELECT capri_research_loop.tick();');
