#define _XOPEN_SOURCE 700
#define _POSIX_C_SOURCE 200809L
#include "capri_session_store.h"

#include <sqlite3.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <pthread.h>

struct CapriSessionStore {
    sqlite3 *db;
    pthread_mutex_t mutex;
    char *path;
    size_t max_messages, max_input, max_output, max_tool;
};

#define RETURN_UNLOCK(store, value) do { pthread_mutex_unlock(&(store)->mutex); return (value); } while (0)

static bool utf8_valid(const unsigned char *s, size_t n, size_t *characters) {
    size_t i = 0u, count = 0u;
    while (i < n) {
        unsigned char a=s[i]; size_t width=0u;
        if (a < 0x80u) width=1u;
        else if (a>=0xC2u && a<=0xDFu) width=2u;
        else if (a>=0xE0u && a<=0xEFu) width=3u;
        else if (a>=0xF0u && a<=0xF4u) width=4u;
        else return false;
        if (i+width>n) return false;
        if (width>=2u && (s[i+1u]<0x80u || s[i+1u]>0xBFu)) return false;
        if (width>=3u) {
            unsigned char b=s[i+1u], c=s[i+2u];
            if (c<0x80u || c>0xBFu) return false;
            if (a==0xE0u && (b<0xA0u || b>0xBFu)) return false;
            else if (a==0xEDu && (b<0x80u || b>0x9Fu)) return false;
            else if (a!=0xE0u && a!=0xEDu && (b<0x80u || b>0xBFu)) return false;
        }
        if (width==4u) {
            unsigned char b=s[i+1u], c=s[i+2u], d=s[i+3u];
            if (c<0x80u || c>0xBFu || d<0x80u || d>0xBFu) return false;
            if (a==0xF0u && (b<0x90u || b>0xBFu)) return false;
            else if (a==0xF4u && (b<0x80u || b>0x8Fu)) return false;
            else if (a!=0xF0u && a!=0xF4u && (b<0x80u || b>0xBFu)) return false;
        }
        i+=width; ++count;
    }
    if (characters) *characters=count;
    return true;
}
static bool unicode_space(uint32_t cp) {
    return (cp>=0x09u&&cp<=0x0Du)||cp==0x20u||cp==0x85u||cp==0xA0u||cp==0x1680u||
      (cp>=0x2000u&&cp<=0x200Au)||cp==0x2028u||cp==0x2029u||cp==0x202Fu||cp==0x205Fu||cp==0x3000u;
}
static bool has_non_whitespace(const unsigned char *s,size_t n) {
    size_t i=0u;
    while(i<n){uint32_t cp=s[i];size_t width=1u;
        if(s[i]>=0xF0u){width=4u;cp=((uint32_t)(s[i]&0x07u)<<18u)|((uint32_t)(s[i+1u]&0x3Fu)<<12u)|((uint32_t)(s[i+2u]&0x3Fu)<<6u)|(uint32_t)(s[i+3u]&0x3Fu);}
        else if(s[i]>=0xE0u){width=3u;cp=((uint32_t)(s[i]&0x0Fu)<<12u)|((uint32_t)(s[i+1u]&0x3Fu)<<6u)|(uint32_t)(s[i+2u]&0x3Fu);}
        else if(s[i]>=0xC2u){width=2u;cp=((uint32_t)(s[i]&0x1Fu)<<6u)|(uint32_t)(s[i+1u]&0x3Fu);}
        if(!unicode_space(cp)) return true;
        i+=width;
    }
    return false;
}
static bool text_ok(const char *s, size_t max, bool nonblank) {
    if (!s) return false;
    size_t n=strlen(s), chars=0u;
    if (n==0u || n>max || !utf8_valid((const unsigned char *)s,n,&chars)) return false;
    return !nonblank || has_non_whitespace((const unsigned char *)s,n);
}
static CapriSessionError map_sqlite(int rc) {
    if (rc==SQLITE_NOMEM) return CAPRI_SESSION_NO_MEMORY;
    if (rc==SQLITE_BUSY || rc==SQLITE_LOCKED || rc==SQLITE_CONSTRAINT) return CAPRI_SESSION_CONFLICT;
    return CAPRI_SESSION_DATABASE;
}
static bool exec_sql(sqlite3 *db, const char *sql) { return sqlite3_exec(db,sql,NULL,NULL,NULL)==SQLITE_OK; }
static bool utc_now(char out[32]) {
    time_t now=time(NULL); struct tm tmv;
    if (now==(time_t)-1 || gmtime_r(&now,&tmv)==NULL) return false;
    return strftime(out,32u,"%Y-%m-%dT%H:%M:%SZ",&tmv)>0u;
}
static bool random_uuid(char out[37]) {
    unsigned char b[16]; size_t got=0u;
    int fd=open("/dev/urandom",O_RDONLY);
    if(fd<0) return false;
    while(got<sizeof b) { ssize_t n=read(fd,b+got,sizeof b-got); if(n<0 && errno==EINTR) continue; if(n<=0){close(fd);return false;} got+=(size_t)n; }
    close(fd); b[6]=(unsigned char)((b[6]&0x0Fu)|0x40u); b[8]=(unsigned char)((b[8]&0x3Fu)|0x80u);
    (void)snprintf(out,37u,"%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
      b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7],b[8],b[9],b[10],b[11],b[12],b[13],b[14],b[15]);
    return true;
}
static bool safe_path(const char *path, char **absolute_out) {
    if (!text_ok(path,PATH_MAX-1u,true)) return false;
    char *raw=NULL;
    if (path[0]=='/') raw=strdup(path);
    else {
        char cwd[PATH_MAX]; if(!getcwd(cwd,sizeof cwd)) return false;
        size_t n=strlen(cwd)+strlen(path)+2u; raw=malloc(n);
        if(raw) (void)snprintf(raw,n,"%s/%s",cwd,path);
    }
    if(!raw) return false;
    char *slash=strrchr(raw,'/');
    if(!slash || slash[1]=='\0' || strcmp(slash+1,".")==0 || strcmp(slash+1,"..")==0) {free(raw);return false;}
    char *base=strdup(slash+1); *slash='\0';
    if(!base){free(raw);return false;}
    const char *parent=raw[0]?raw:"/";
    char *resolved=realpath(parent,NULL);
    if(!resolved || strcmp(parent,resolved)!=0) {free(base);free(raw);free(resolved);return false;}
    struct stat ps;
    if(lstat(resolved,&ps)!=0 || !S_ISDIR(ps.st_mode) || (ps.st_mode&077u)!=0u || ps.st_uid!=geteuid()) {free(base);free(raw);free(resolved);return false;}
    size_t n=strlen(resolved)+strlen(base)+2u; char *absolute=malloc(n);
    if(absolute) (void)snprintf(absolute,n,"%s/%s",resolved,base);
    free(base);free(raw);free(resolved);if(!absolute)return false;
    struct stat fs;
    if(lstat(absolute,&fs)==0) {
        if(!S_ISREG(fs.st_mode) || fs.st_uid!=geteuid() || fs.st_nlink!=1 || (fs.st_mode&0777u)!=0600u) {free(absolute);return false;}
    } else if(errno!=ENOENT) {free(absolute);return false;}
    *absolute_out=absolute; return true;
}
static bool store_path_safe(const CapriSessionStore *store) {
    char *copy=strdup(store->path); if(!copy)return false;
    char *slash=strrchr(copy,'/'); if(!slash){free(copy);return false;} *slash='\0';
    const char *parent=copy[0]?copy:"/"; char *resolved=realpath(parent,NULL);
    struct stat ps,fs;
    bool ok=resolved&&strcmp(parent,resolved)==0&&lstat(resolved,&ps)==0&&S_ISDIR(ps.st_mode)&&ps.st_uid==geteuid()&&(ps.st_mode&077u)==0u&&lstat(store->path,&fs)==0&&S_ISREG(fs.st_mode)&&fs.st_uid==geteuid()&&fs.st_nlink==1&&(fs.st_mode&0777u)==0600u;
    free(resolved);free(copy);return ok;
}

static bool schema(sqlite3 *db) {
    const char *sql=
      "PRAGMA foreign_keys=ON; PRAGMA recursive_triggers=ON; PRAGMA trusted_schema=OFF; PRAGMA synchronous=FULL; PRAGMA journal_mode=WAL;"
      "CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>=0),closed INTEGER NOT NULL CHECK(closed IN(0,1)),messages_json TEXT NOT NULL CHECK(json_valid(messages_json) AND json_type(messages_json)='array'));"
      "CREATE INDEX IF NOT EXISTS sessions_updated_at ON sessions(updated_at);"
      "CREATE TABLE IF NOT EXISTS session_turn_leases(session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,owner_token TEXT NOT NULL,expires_at TEXT NOT NULL);"
      "CREATE TABLE IF NOT EXISTS session_owners(session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,principal_id TEXT NOT NULL,created_at TEXT NOT NULL);"
      "CREATE TRIGGER IF NOT EXISTS session_owners_immutable_update BEFORE UPDATE ON session_owners BEGIN SELECT RAISE(ABORT,'session owner is immutable'); END;"
      "CREATE TRIGGER IF NOT EXISTS session_owners_immutable_delete BEFORE DELETE ON session_owners BEGIN SELECT RAISE(ABORT,'session owner is immutable'); END;"
      "CREATE TRIGGER IF NOT EXISTS session_owners_immutable_insert BEFORE INSERT ON session_owners WHEN EXISTS(SELECT 1 FROM session_owners WHERE session_id=NEW.session_id) BEGIN SELECT RAISE(ABORT,'session owner is immutable'); END;";
    return exec_sql(db,sql);
}
CapriSessionStore *capri_session_store_open(const char *path,size_t max_messages,size_t max_input,size_t max_output,size_t max_tool,CapriSessionError *error) {
    if(error) *error=CAPRI_SESSION_INVALID;
    if(max_messages<2u || max_messages>100000u || max_input==0u || max_input>1048576u || max_output==0u || max_output>1048576u || max_tool==0u || max_tool>1048576u || sqlite3_libversion_number()<3038000) return NULL;
    char *absolute=NULL; if(!safe_path(path,&absolute)) return NULL;
    int flags=O_RDWR|O_CREAT;
#ifdef O_NOFOLLOW
    flags|=O_NOFOLLOW;
#endif
    int fd=open(absolute,flags,0600); if(fd<0){free(absolute);if(error)*error=CAPRI_SESSION_IO;return NULL;}
    struct stat st; bool ok=fstat(fd,&st)==0 && S_ISREG(st.st_mode) && st.st_uid==geteuid() && st.st_nlink==1 && fchmod(fd,0600)==0;
    close(fd); if(!ok){free(absolute);if(error)*error=CAPRI_SESSION_IO;return NULL;}
    CapriSessionStore *s=calloc(1u,sizeof *s); if(!s){free(absolute);if(error)*error=CAPRI_SESSION_NO_MEMORY;return NULL;}
    s->path=absolute;s->max_messages=max_messages;s->max_input=max_input;s->max_output=max_output;s->max_tool=max_tool;
    if(pthread_mutex_init(&s->mutex,NULL)!=0){free(s->path);free(s);if(error)*error=CAPRI_SESSION_IO;return NULL;}
    int rc=sqlite3_open_v2(absolute,&s->db,SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE|SQLITE_OPEN_FULLMUTEX,NULL);
    if(rc!=SQLITE_OK || !schema(s->db) || !store_path_safe(s)){ if(s->db)sqlite3_close(s->db);pthread_mutex_destroy(&s->mutex);free(s->path);free(s);if(error)*error=CAPRI_SESSION_DATABASE;return NULL; }
    (void)sqlite3_busy_timeout(s->db,5000);
#ifdef SQLITE_DBCONFIG_DEFENSIVE
    (void)sqlite3_db_config(s->db,SQLITE_DBCONFIG_DEFENSIVE,1,NULL);
#endif
    if(error) *error=CAPRI_SESSION_OK;
    return s;
}
void capri_session_store_close(CapriSessionStore *s){if(s){pthread_mutex_lock(&s->mutex);sqlite3_close(s->db);pthread_mutex_unlock(&s->mutex);pthread_mutex_destroy(&s->mutex);free(s->path);free(s);}}
void capri_session_free(CapriSession *s){if(s){free(s->messages_json);memset(s,0,sizeof *s);}}
static CapriSessionError validate_history(CapriSessionStore *store,const char *json,int64_t version) {
    sqlite3_stmt *st=NULL; int rc=sqlite3_prepare_v2(store->db,"SELECT json_valid(?1),json_type(?1)",-1,&st,NULL);
    if(rc!=SQLITE_OK)return map_sqlite(rc);
    sqlite3_bind_text(st,1,json,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);
    bool valid=rc==SQLITE_ROW&&sqlite3_column_int(st,0)==1&&sqlite3_column_type(st,1)==SQLITE_TEXT&&strcmp((const char*)sqlite3_column_text(st,1),"array")==0;
    sqlite3_finalize(st);if(!valid)return CAPRI_SESSION_CORRUPT;
    rc=sqlite3_prepare_v2(store->db,"SELECT json_type(msg.value),json_extract(msg.value,'$.role'),json_extract(msg.value,'$.content'),(SELECT count(*) FROM json_each(msg.value)),json_type(msg.value,'$.role'),json_type(msg.value,'$.content') FROM json_each(?1) AS msg ORDER BY CAST(msg.key AS INTEGER)",-1,&st,NULL);
    if(rc!=SQLITE_OK)return map_sqlite(rc);
    sqlite3_bind_text(st,1,json,-1,SQLITE_TRANSIENT);size_t count=0u,users=0u;char previous[33]={0};bool in_turn=false;CapriSessionError result=CAPRI_SESSION_OK;
    while((rc=sqlite3_step(st))==SQLITE_ROW){
        const unsigned char *type=sqlite3_column_text(st,0),*role=sqlite3_column_text(st,1),*content=sqlite3_column_text(st,2);
        int rb=sqlite3_column_bytes(st,1),cb=sqlite3_column_bytes(st,2);
        if(!type||strcmp((const char*)type,"object")!=0||sqlite3_column_int(st,3)!=2||!role||!content||rb<=0||cb<=0||memchr(role,0,(size_t)rb)!=NULL||!sqlite3_column_text(st,4)||strcmp((const char*)sqlite3_column_text(st,4),"text")!=0||!sqlite3_column_text(st,5)||strcmp((const char*)sqlite3_column_text(st,5),"text")!=0){result=CAPRI_SESSION_CORRUPT;break;}
        size_t rchars=0u,cchars=0u;if(!utf8_valid(role,(size_t)rb,&rchars)||!utf8_valid(content,(size_t)cb,&cchars)||rchars>32u){result=CAPRI_SESSION_CORRUPT;break;}
        const char *r=(const char*)role;size_t limit=0u;
        if(strcmp(r,"user")==0){if(count>0u&&strcmp(previous,"assistant")!=0){result=CAPRI_SESSION_CORRUPT;break;}in_turn=true;limit=store->max_input;++users;}
        else if(strcmp(r,"tool")==0){if(!in_turn||(strcmp(previous,"assistant")!=0&&strcmp(previous,"tool")!=0)){result=CAPRI_SESSION_CORRUPT;break;}limit=store->max_tool;}
        else if(strcmp(r,"assistant")==0){if(!in_turn){result=CAPRI_SESSION_CORRUPT;break;}limit=store->max_output;}
        else {result=CAPRI_SESSION_CORRUPT;break;}
        bool nonblank=has_non_whitespace(content,(size_t)cb);
        if(!nonblank||cchars>limit){result=CAPRI_SESSION_CORRUPT;break;}
        memset(previous,0,sizeof previous);memcpy(previous,r,rchars);++count;
        if(count>store->max_messages){result=CAPRI_SESSION_CORRUPT;break;}
    }
    if(result==CAPRI_SESSION_OK&&rc!=SQLITE_DONE)result=map_sqlite(rc);
    if(result==CAPRI_SESSION_OK&&(users!=(size_t)version||(count>0u&&strcmp(previous,"assistant")!=0)||(count==0u&&version!=0)))result=CAPRI_SESSION_CORRUPT;
    sqlite3_finalize(st);return result;
}
static CapriSessionError read_row(CapriSessionStore *store,sqlite3_stmt *st,CapriSession *out) {
    memset(out,0,sizeof *out);
    const unsigned char *sid=sqlite3_column_text(st,0),*created=sqlite3_column_text(st,1),*updated=sqlite3_column_text(st,2),*json=sqlite3_column_text(st,5);
    if(!sid||!created||!updated||!json) return CAPRI_SESSION_CORRUPT;
    if(strlen((const char*)sid)>=sizeof out->session_id || !text_ok((const char*)created,64u,true) || !text_ok((const char*)updated,64u,true)) return CAPRI_SESSION_CORRUPT;
    if(strlen((const char*)created)>=sizeof out->created_at || strlen((const char*)updated)>=sizeof out->updated_at) return CAPRI_SESSION_CORRUPT;
    strcpy(out->session_id,(const char*)sid);strcpy(out->created_at,(const char*)created);strcpy(out->updated_at,(const char*)updated);
    out->version=sqlite3_column_int64(st,3);out->closed=sqlite3_column_int(st,4);
    if(out->version<0||(out->closed!=0&&out->closed!=1))return CAPRI_SESSION_CORRUPT;
    CapriSessionError valid=validate_history(store,(const char*)json,out->version);if(valid!=CAPRI_SESSION_OK)return valid;
    out->messages_json=strdup((const char*)json); if(!out->messages_json)return CAPRI_SESSION_NO_MEMORY;
    return CAPRI_SESSION_OK;
}
static CapriSessionError select_owned(CapriSessionStore *s,const char *id,const char *principal,CapriSession *out) {
    const char *sql="SELECT s.session_id,s.created_at,s.updated_at,s.version,s.closed,s.messages_json FROM sessions s JOIN session_owners o ON o.session_id=s.session_id WHERE s.session_id=?1 AND o.principal_id=?2";
    sqlite3_stmt *st=NULL; int rc=sqlite3_prepare_v2(s->db,sql,-1,&st,NULL);if(rc!=SQLITE_OK)return map_sqlite(rc);
    sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,principal,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);
    CapriSessionError e=rc==SQLITE_ROW?read_row(s,st,out):(rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));sqlite3_finalize(st);return e;
}
CapriSessionError capri_session_create_for_principal(CapriSessionStore *s,const char *principal,CapriSession *out) {
    if(!s||!out||!text_ok(principal,256u,true))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    char id[37],now[32];if(!random_uuid(id)||!utc_now(now)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    char *empty_json=strdup("[]");if(!empty_json) RETURN_UNLOCK(s,CAPRI_SESSION_NO_MEMORY);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE")){free(empty_json);RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"INSERT INTO sessions VALUES(?1,?2,?2,0,0,'[]')",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,now,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);
    if(rc==SQLITE_DONE){rc=sqlite3_prepare_v2(s->db,"INSERT INTO session_owners VALUES(?1,?2,?3)",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,principal,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,now,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);}
    if(rc!=SQLITE_DONE){free(empty_json);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}if(!exec_sql(s->db,"COMMIT")){free(empty_json);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}
    memset(out,0,sizeof *out);strcpy(out->session_id,id);strcpy(out->created_at,now);strcpy(out->updated_at,now);out->messages_json=empty_json;RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_get_for_principal(CapriSessionStore *s,const char *id,const char *principal,CapriSession *out) {
    if(!s||!out||!text_ok(id,36u,true)||!text_ok(principal,256u,true))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    CapriSessionError result=select_owned(s,id,principal,out);
    RETURN_UNLOCK(s,result);
}
static CapriSessionError validate_turn(CapriSessionStore *s,const char *json,size_t *count) {
    if(!json||strlen(json)>8u*(s->max_input+s->max_output+s->max_tool+128u))return CAPRI_SESSION_INVALID;
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT json_valid(?1),json_type(?1)",-1,&st,NULL);if(rc!=SQLITE_OK)return map_sqlite(rc);
    sqlite3_bind_text(st,1,json,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);bool valid=rc==SQLITE_ROW&&sqlite3_column_int(st,0)==1&&sqlite3_column_type(st,1)==SQLITE_TEXT&&strcmp((const char*)sqlite3_column_text(st,1),"array")==0;sqlite3_finalize(st);if(!valid)return CAPRI_SESSION_INVALID;
    rc=sqlite3_prepare_v2(s->db,"SELECT CAST(msg.key AS INTEGER),json_type(msg.value),json_extract(msg.value,'$.role'),json_extract(msg.value,'$.content'),(SELECT count(*) FROM json_each(msg.value)),json_type(msg.value,'$.role'),json_type(msg.value,'$.content') FROM json_each(?1) AS msg ORDER BY CAST(msg.key AS INTEGER)",-1,&st,NULL);if(rc!=SQLITE_OK)return map_sqlite(rc);
    sqlite3_bind_text(st,1,json,-1,SQLITE_TRANSIENT);size_t n=0u;char previous[33]={0};bool first=true;CapriSessionError result=CAPRI_SESSION_OK;
    while((rc=sqlite3_step(st))==SQLITE_ROW){
        const unsigned char *type=sqlite3_column_text(st,1),*role=sqlite3_column_text(st,2),*content=sqlite3_column_text(st,3);int role_bytes=sqlite3_column_bytes(st,2),content_bytes=sqlite3_column_bytes(st,3);
        if(!type||strcmp((const char*)type,"object")!=0||sqlite3_column_int(st,4)!=2||!role||!content||role_bytes<=0||content_bytes<=0||memchr(role,0,(size_t)role_bytes)!=NULL||!sqlite3_column_text(st,5)||strcmp((const char*)sqlite3_column_text(st,5),"text")!=0||!sqlite3_column_text(st,6)||strcmp((const char*)sqlite3_column_text(st,6),"text")!=0){result=CAPRI_SESSION_INVALID;break;}
        size_t role_chars=0u,content_chars=0u;if(!utf8_valid(role,(size_t)role_bytes,&role_chars)||!utf8_valid(content,(size_t)content_bytes,&content_chars)||role_chars>32u){result=CAPRI_SESSION_INVALID;break;}
        const char *r=(const char*)role;size_t limit=0u;
        if(first){if(strcmp(r,"user")!=0){result=CAPRI_SESSION_INVALID;break;}limit=s->max_input;}
        else if(strcmp(r,"user")==0){result=CAPRI_SESSION_INVALID;break;}
        else if(strcmp(r,"tool")==0){if(previous[0]==0 || (strcmp(previous,"assistant")!=0&&strcmp(previous,"tool")!=0)){result=CAPRI_SESSION_INVALID;break;}limit=s->max_tool;}
        else if(strcmp(r,"assistant")==0)limit=s->max_output;
        else {result=CAPRI_SESSION_INVALID;break;}
        bool nonblank=has_non_whitespace(content,(size_t)content_bytes);
        if(!nonblank){result=CAPRI_SESSION_INVALID;break;}if(content_chars>limit){result=CAPRI_SESSION_LIMIT;break;}
        memset(previous,0,sizeof previous);memcpy(previous,r,role_chars);first=false;++n;
    }
    if(result==CAPRI_SESSION_OK && rc!=SQLITE_DONE)result=map_sqlite(rc);
    if(result==CAPRI_SESSION_OK&&(n<2u||previous[0]==0||strcmp(previous,"assistant")!=0)){result=CAPRI_SESSION_INVALID;}
    sqlite3_finalize(st);if(count)*count=n;return result;
}
CapriSessionError capri_session_commit_turn_for_principal(CapriSessionStore *s,const char *id,const char *principal,int64_t expected,const char *turn_json,const char *lease_owner,CapriSession *out) {
    if(!s||!out||!text_ok(id,36u,true)||!text_ok(principal,256u,true)||expected<0)return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    size_t turn_count=0u;CapriSessionError e=validate_turn(s,turn_json,&turn_count);if(e!=CAPRI_SESSION_OK) RETURN_UNLOCK(s,e);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE")) RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    CapriSession current={0};e=select_owned(s,id,principal,&current);if(e!=CAPRI_SESSION_OK)goto fail;
    if(current.closed){e=CAPRI_SESSION_CLOSED;goto fail;}
    if(current.version!=expected){e=CAPRI_SESSION_CONFLICT;goto fail;}
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT owner_token,expires_at,(julianday(expires_at)>julianday('now')) FROM session_turn_leases WHERE session_id=?1",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}if(rc==SQLITE_ROW){const char *owner=(const char*)sqlite3_column_text(st,0);const char *expiry=(const char*)sqlite3_column_text(st,1);if(!owner||!expiry||sqlite3_column_int(st,2)!=1||!lease_owner||strcmp(owner,lease_owner)!=0)e=CAPRI_SESSION_CONFLICT;}else if(rc!=SQLITE_DONE)e=map_sqlite(rc);else if(lease_owner)e=CAPRI_SESSION_CONFLICT;sqlite3_finalize(st);if(e!=CAPRI_SESSION_OK)goto fail;
    st=NULL;rc=sqlite3_prepare_v2(s->db,"SELECT json_array_length(?1), (SELECT count(*) FROM json_each(?1) WHERE json_extract(value,'$.role')='user')",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,current.messages_json,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}size_t old_count=rc==SQLITE_ROW?(size_t)sqlite3_column_int64(st,0):0u;size_t old_users=rc==SQLITE_ROW?(size_t)sqlite3_column_int64(st,1):0u;sqlite3_finalize(st);if(rc!=SQLITE_ROW){e=CAPRI_SESSION_CORRUPT;goto fail;}
    if(old_count+turn_count>s->max_messages){e=CAPRI_SESSION_LIMIT;goto fail;}
    if(old_users!=(size_t)current.version){e=CAPRI_SESSION_CORRUPT;goto fail;}
    st=NULL;const char *append_sql="SELECT json_group_array(json(value)) FROM (SELECT value,0 AS grp,CAST(key AS INTEGER) AS seq FROM json_each(?1) UNION ALL SELECT value,1 AS grp,CAST(key AS INTEGER) AS seq FROM json_each(?2) ORDER BY grp,seq)";
    rc=sqlite3_prepare_v2(s->db,append_sql,-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,current.messages_json,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,turn_json,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}char *combined=rc==SQLITE_ROW?strdup((const char*)sqlite3_column_text(st,0)):NULL;sqlite3_finalize(st);if(!combined){e=rc==SQLITE_ROW?CAPRI_SESSION_NO_MEMORY:CAPRI_SESSION_DATABASE;goto fail;}
    char now[32];if(!utc_now(now)){free(combined);e=CAPRI_SESSION_IO;goto fail;}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"UPDATE sessions SET updated_at=?1,version=version+1,messages_json=?2 WHERE session_id=?3 AND version=?4 AND closed=0",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,now,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,combined,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,id,-1,SQLITE_TRANSIENT);sqlite3_bind_int64(st,4,expected);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_DONE){e=map_sqlite(rc);goto fail;}if(sqlite3_changes(s->db)!=1){e=CAPRI_SESSION_CONFLICT;goto fail;}
    if(!exec_sql(s->db,"COMMIT")){free(combined);e=CAPRI_SESSION_DATABASE;goto fail;}
    *out=current; memset(&current,0,sizeof current); out->version=expected+1; strcpy(out->updated_at,now); free(out->messages_json); out->messages_json=combined;
    RETURN_UNLOCK(s,CAPRI_SESSION_OK);
fail:
    capri_session_free(&current);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,e);
}

static bool lease_input(const char *id,const char *principal,const char *token,double seconds) {
    return text_ok(id,36u,true)&&text_ok(principal,256u,true)&&text_ok(token,128u,true)&&seconds>=3.0&&seconds<=3600.0;
}
static bool lease_expiry(char out[40],double seconds) {
    struct timespec ts; if(clock_gettime(CLOCK_REALTIME,&ts)!=0)return false;
    time_t whole=ts.tv_sec+(time_t)seconds; long nanos=ts.tv_nsec+(long)((seconds-(double)(time_t)seconds)*1000000000.0);
    if(nanos>=1000000000L){++whole;nanos-=1000000000L;}
    struct tm tmv; if(gmtime_r(&whole,&tmv)==NULL)return false;
    char base[24];if(strftime(base,sizeof base,"%Y-%m-%dT%H:%M:%S",&tmv)==0u)return false;
    int written=snprintf(out,40u,"%s.%09ldZ",base,nanos);return written>0&&written<40;
}
CapriSessionError capri_session_claim_turn_lease_for_principal(CapriSessionStore *s,const char *id,const char *principal,const char *token,double seconds) {
    if(!s||!lease_input(id,principal,token,seconds))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    char expiry[40];if(!lease_expiry(expiry,seconds)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE")) RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT s.closed FROM sessions s JOIN session_owners o ON o.session_id=s.session_id WHERE s.session_id=?1 AND o.principal_id=?2",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,principal,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}if(rc!=SQLITE_ROW){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));}if(sqlite3_column_int(st,0)!=0){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CLOSED);}sqlite3_finalize(st);
    st=NULL;rc=sqlite3_prepare_v2(s->db,"SELECT owner_token,(julianday(expires_at)>julianday('now')) FROM session_turn_leases WHERE session_id=?1",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}if(rc==SQLITE_ROW){const char *old=(const char*)sqlite3_column_text(st,0);int live=sqlite3_column_int(st,1);if(!old||(live&&strcmp(old,token)!=0)||(!live&&strcmp(old,token)==0)){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CONFLICT);}sqlite3_finalize(st);st=NULL;rc=sqlite3_prepare_v2(s->db,"UPDATE session_turn_leases SET owner_token=?1,expires_at=?2 WHERE session_id=?3",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,token,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,expiry,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);}else if(rc==SQLITE_DONE){sqlite3_finalize(st);st=NULL;rc=sqlite3_prepare_v2(s->db,"INSERT INTO session_turn_leases VALUES(?1,?2,?3)",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,token,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,expiry,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);}else{sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}
    if(rc!=SQLITE_DONE){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_renew_turn_lease_for_principal(CapriSessionStore *s,const char *id,const char *principal,const char *token,double seconds) {
    if(!s||!lease_input(id,principal,token,seconds))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    char expiry[40];if(!lease_expiry(expiry,seconds)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE")) RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT 1 FROM session_owners WHERE session_id=?1 AND principal_id=?2",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,principal,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_ROW){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"UPDATE session_turn_leases SET expires_at=?1 WHERE session_id=?2 AND owner_token=?3 AND julianday(expires_at)>julianday('now')",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,expiry,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,token,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_DONE){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}if(sqlite3_changes(s->db)!=1){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CONFLICT);}if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_release_turn_lease_for_principal(CapriSessionStore *s,const char *id,const char *principal,const char *token,int *released) {
    if(!s||!text_ok(id,36u,true)||!text_ok(principal,256u,true)||!text_ok(token,128u,true)||!released) return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    *released=0;
    if(!exec_sql(s->db,"BEGIN IMMEDIATE")) RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT 1 FROM session_owners WHERE session_id=?1 AND principal_id=?2",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,principal,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_ROW){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"DELETE FROM session_turn_leases WHERE session_id=?1 AND owner_token=?2 AND julianday(expires_at)>julianday('now')",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,token,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_DONE){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}*released=sqlite3_changes(s->db)==1;if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_close_for_principal(CapriSessionStore *s,const char *id,const char *principal,CapriSession *out) {
    if(!s||!out||!text_ok(id,36u,true)||!text_ok(principal,256u,true))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE")) RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    CapriSession current={0};CapriSessionError e=select_owned(s,id,principal,&current);if(e!=CAPRI_SESSION_OK){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,e);}
    if(!current.closed){char now[32];if(!utc_now(now)){capri_session_free(&current);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_IO);}sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"UPDATE sessions SET closed=1,updated_at=?1 WHERE session_id=?2",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,now,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_DONE){capri_session_free(&current);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}current.closed=1;strcpy(current.updated_at,now);}
    if(!exec_sql(s->db,"COMMIT")){capri_session_free(&current);RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}*out=current;RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
const char *capri_session_error_string(CapriSessionError e){static const char *const m[]={"ok","invalid input","filesystem operation failed","SQLite operation failed","session not found","session closed","session conflict","resource limit reached","persisted session is corrupt","out of memory"};return e>=CAPRI_SESSION_OK&&e<=CAPRI_SESSION_NO_MEMORY?m[e]:"unknown session error";}
