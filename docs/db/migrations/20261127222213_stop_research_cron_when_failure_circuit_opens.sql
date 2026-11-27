CREATE OR REPLACE FUNCTION capri_research_loop.accept_response(p_id bigint, p_status integer, p_body text, p_transport_error boolean DEFAULT false)
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
   IF EXISTS(SELECT 1 FROM capri_research_loop.control WHERE id AND NOT enabled) THEN
     PERFORM cron.alter_job(jobid,active:=false) FROM cron.job WHERE jobname='capri_public_source_collector';
   END IF;
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
REVOKE ALL ON FUNCTION capri_research_loop.accept_response(bigint,integer,text,boolean) FROM PUBLIC,anon,authenticated,service_role;
