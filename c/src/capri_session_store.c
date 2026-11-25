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
static bool sqlite_text_ok(sqlite3_stmt *st,int column,size_t max_bytes,bool nonblank) {
    const unsigned char *value=sqlite3_column_text(st,column);int bytes=sqlite3_column_bytes(st,column);size_t characters=0u;
    if(!value||bytes<=0||(size_t)bytes>max_bytes||memchr(value,0,(size_t)bytes)!=NULL||!utf8_valid(value,(size_t)bytes,&characters))return false;
    return !nonblank||has_non_whitespace(value,(size_t)bytes);
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
static bool lease_timestamp_aware(const unsigned char *value,int bytes) {
    if(!value||bytes<=0)return false;
    size_t n=(size_t)bytes;
    if(value[n-1u]=='Z'||value[n-1u]=='z')return true;
    if(n<6u)return false;
    const unsigned char *offset=value+n-6u;
    return (offset[0]=='+'||offset[0]=='-')&&offset[1]>='0'&&offset[1]<='9'&&offset[2]>='0'&&offset[2]<='9'&&offset[3]==':'&&offset[4]>='0'&&offset[4]<='9'&&offset[5]>='0'&&offset[5]<='9';
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
      "CREATE INDEX IF NOT EXISTS session_owners_principal_id ON session_owners(principal_id);"
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
    int sqlite_flags=SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE|SQLITE_OPEN_FULLMUTEX;
#ifdef SQLITE_OPEN_NOFOLLOW
    sqlite_flags|=SQLITE_OPEN_NOFOLLOW;
#endif
    int rc=sqlite3_open_v2(absolute,&s->db,sqlite_flags,NULL);
    if(rc==SQLITE_OK) (void)sqlite3_busy_timeout(s->db,5000);
    if(rc!=SQLITE_OK || !schema(s->db) || !store_path_safe(s)){ if(s->db)sqlite3_close(s->db);pthread_mutex_destroy(&s->mutex);free(s->path);free(s);if(error)*error=CAPRI_SESSION_DATABASE;return NULL; }
#ifdef SQLITE_DBCONFIG_DEFENSIVE
    (void)sqlite3_db_config(s->db,SQLITE_DBCONFIG_DEFENSIVE,1,NULL);
#endif
    if(error) *error=CAPRI_SESSION_OK;
    return s;
}
void capri_session_store_close(CapriSessionStore *s){if(s){pthread_mutex_lock(&s->mutex);sqlite3_close(s->db);pthread_mutex_unlock(&s->mutex);pthread_mutex_destroy(&s->mutex);free(s->path);free(s);}}
void capri_session_free(CapriSession *s){if(s){free(s->messages_json);memset(s,0,sizeof *s);}}
static CapriSessionError validate_history(CapriSessionStore *store,sqlite3 *db,const char *json,int64_t version) {
    sqlite3_stmt *st=NULL; int rc=sqlite3_prepare_v2(db,"SELECT json_valid(?1),json_type(?1)",-1,&st,NULL);
    if(rc!=SQLITE_OK)return map_sqlite(rc);
    sqlite3_bind_text(st,1,json,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);
    bool valid=rc==SQLITE_ROW&&sqlite3_column_int(st,0)==1&&sqlite3_column_type(st,1)==SQLITE_TEXT&&strcmp((const char*)sqlite3_column_text(st,1),"array")==0;
    sqlite3_finalize(st);if(!valid)return CAPRI_SESSION_CORRUPT;
    rc=sqlite3_prepare_v2(db,"SELECT json_type(msg.value),json_extract(msg.value,'$.role'),json_extract(msg.value,'$.content'),(SELECT count(*) FROM json_each(msg.value)),json_type(msg.value,'$.role'),json_type(msg.value,'$.content') FROM json_each(?1) AS msg ORDER BY CAST(msg.key AS INTEGER)",-1,&st,NULL);
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
static CapriSessionError read_row(CapriSessionStore *store,sqlite3 *db,sqlite3_stmt *st,CapriSession *out) {
    memset(out,0,sizeof *out);
    const unsigned char *sid=sqlite3_column_text(st,0),*created=sqlite3_column_text(st,1),*updated=sqlite3_column_text(st,2),*json=sqlite3_column_text(st,5);
    if(!sid||!created||!updated||!json) return CAPRI_SESSION_CORRUPT;
    if(strlen((const char*)sid)>=sizeof out->session_id || !text_ok((const char*)sid,36u,true) || !text_ok((const char*)created,64u,true) || !text_ok((const char*)updated,64u,true)) return CAPRI_SESSION_CORRUPT;
    if(strlen((const char*)created)>=sizeof out->created_at || strlen((const char*)updated)>=sizeof out->updated_at) return CAPRI_SESSION_CORRUPT;
    strcpy(out->session_id,(const char*)sid);strcpy(out->created_at,(const char*)created);strcpy(out->updated_at,(const char*)updated);
    out->version=sqlite3_column_int64(st,3);out->closed=sqlite3_column_int(st,4);
    if(out->version<0||(out->closed!=0&&out->closed!=1))return CAPRI_SESSION_CORRUPT;
    CapriSessionError valid=validate_history(store,db,(const char*)json,out->version);if(valid!=CAPRI_SESSION_OK)return valid;
    out->messages_json=strdup((const char*)json); if(!out->messages_json)return CAPRI_SESSION_NO_MEMORY;
    return CAPRI_SESSION_OK;
}
static CapriSessionError select_owned(CapriSessionStore *s,const char *id,const char *principal,CapriSession *out) {
    const char *sql="SELECT s.session_id,s.created_at,s.updated_at,s.version,s.closed,s.messages_json FROM sessions s JOIN session_owners o ON o.session_id=s.session_id WHERE s.session_id=?1 AND o.principal_id=?2";
    sqlite3_stmt *st=NULL; int rc=sqlite3_prepare_v2(s->db,sql,-1,&st,NULL);if(rc!=SQLITE_OK)return map_sqlite(rc);
    sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,principal,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);
    CapriSessionError e=rc==SQLITE_ROW?read_row(s,s->db,st,out):(rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));sqlite3_finalize(st);return e;
}
static CapriSessionError select_unowned(CapriSessionStore *s,const char *id,CapriSession *out) {
    const char *sql="SELECT s.session_id,s.created_at,s.updated_at,s.version,s.closed,s.messages_json FROM sessions s WHERE s.session_id=?1 AND NOT EXISTS(SELECT 1 FROM session_owners o WHERE o.session_id=s.session_id)";
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,sql,-1,&st,NULL);if(rc!=SQLITE_OK)return map_sqlite(rc);
    sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);
    CapriSessionError e=rc==SQLITE_ROW?read_row(s,s->db,st,out):(rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));sqlite3_finalize(st);return e;
}
static CapriSessionError validate_backup_snapshot(CapriSessionStore *store,sqlite3 *db) {
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(db,"PRAGMA integrity_check",-1,&st,NULL);
    if(rc!=SQLITE_OK)return map_sqlite(rc);
    rc=sqlite3_step(st);bool integrity=rc==SQLITE_ROW&&sqlite3_column_text(st,0)&&strcmp((const char*)sqlite3_column_text(st,0),"ok")==0;sqlite3_finalize(st);
    if(!integrity)return CAPRI_SESSION_CORRUPT;
    rc=sqlite3_prepare_v2(db,"PRAGMA foreign_key_check",-1,&st,NULL);if(rc!=SQLITE_OK)return map_sqlite(rc);
    rc=sqlite3_step(st);sqlite3_finalize(st);if(rc!=SQLITE_DONE)return rc==SQLITE_ROW?CAPRI_SESSION_CORRUPT:map_sqlite(rc);
    rc=sqlite3_prepare_v2(db,"SELECT session_id,created_at,updated_at,version,closed,messages_json FROM sessions ORDER BY created_at,session_id",-1,&st,NULL);if(rc!=SQLITE_OK)return map_sqlite(rc);
    CapriSessionError result=CAPRI_SESSION_OK;
    while((rc=sqlite3_step(st))==SQLITE_ROW){CapriSession row={0};result=read_row(store,db,st,&row);capri_session_free(&row);if(result!=CAPRI_SESSION_OK)break;}
    if(result==CAPRI_SESSION_OK&&rc!=SQLITE_DONE) result=map_sqlite(rc);
    sqlite3_finalize(st);
    if(result!=CAPRI_SESSION_OK) return result;
    rc=sqlite3_prepare_v2(db,"SELECT session_id,principal_id,created_at FROM session_owners",-1,&st,NULL);if(rc!=SQLITE_OK)return map_sqlite(rc);
    while((rc=sqlite3_step(st))==SQLITE_ROW){
        if(!sqlite_text_ok(st,0,36u,true)||!sqlite_text_ok(st,1,256u,true)||!sqlite_text_ok(st,2,64u,true)||!lease_timestamp_aware(sqlite3_column_text(st,2),sqlite3_column_bytes(st,2))){result=CAPRI_SESSION_CORRUPT;break;}
    }
    if(result==CAPRI_SESSION_OK&&rc!=SQLITE_DONE) result=map_sqlite(rc);
    sqlite3_finalize(st);
    if(result!=CAPRI_SESSION_OK) return result;
    rc=sqlite3_prepare_v2(db,"SELECT session_id,owner_token,expires_at FROM session_turn_leases",-1,&st,NULL);if(rc!=SQLITE_OK)return map_sqlite(rc);
    while((rc=sqlite3_step(st))==SQLITE_ROW){
        if(!sqlite_text_ok(st,0,36u,true)||!sqlite_text_ok(st,1,128u,true)||!sqlite_text_ok(st,2,64u,true)||!lease_timestamp_aware(sqlite3_column_text(st,2),sqlite3_column_bytes(st,2))){result=CAPRI_SESSION_CORRUPT;break;}
    }
    if(result==CAPRI_SESSION_OK&&rc!=SQLITE_DONE) result=map_sqlite(rc);
    sqlite3_finalize(st);
    return result;
}
CapriSessionError capri_session_integrity_check(CapriSessionStore *s) {
    if(!s)return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s))RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    CapriSessionError result=validate_backup_snapshot(s,s->db);
    RETURN_UNLOCK(s,result);
}
CapriSessionError capri_session_backup_to(CapriSessionStore *s,const char *destination_path) {
    if(!s||!text_ok(destination_path,PATH_MAX-1u,true))return CAPRI_SESSION_INVALID;
    char *absolute=NULL;if(!safe_path(destination_path,&absolute))return CAPRI_SESSION_IO;
    if(strcmp(absolute,s->path)==0){free(absolute);return CAPRI_SESSION_INVALID;}
    struct stat existing;if(lstat(absolute,&existing)==0){free(absolute);return CAPRI_SESSION_INVALID;}if(errno!=ENOENT){free(absolute);return CAPRI_SESSION_IO;}
    char *slash=strrchr(absolute,'/');if(!slash){free(absolute);return CAPRI_SESSION_INVALID;}size_t parent_len=(size_t)(slash-absolute);char *parent=malloc(parent_len+1u);if(!parent){free(absolute);return CAPRI_SESSION_NO_MEMORY;}memcpy(parent,absolute,parent_len);parent[parent_len]='\0';
    size_t template_len=strlen(parent)+32u;if(template_len>PATH_MAX){free(parent);free(absolute);return CAPRI_SESSION_INVALID;}char *temporary=malloc(template_len);if(!temporary){free(parent);free(absolute);return CAPRI_SESSION_NO_MEMORY;}
    (void)snprintf(temporary,template_len,"%s/.capri-session-backup-XXXXXX",parent);
    int fd=mkstemp(temporary);if(fd<0){free(temporary);free(parent);free(absolute);return CAPRI_SESSION_IO;}
    bool ok=fchmod(fd,0600)==0&&fsync(fd)==0;close(fd);if(!ok){unlink(temporary);free(temporary);free(parent);free(absolute);return CAPRI_SESSION_IO;}
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)){pthread_mutex_unlock(&s->mutex);unlink(temporary);free(temporary);free(parent);free(absolute);return CAPRI_SESSION_IO;}
    sqlite3 *destination=NULL;int rc=sqlite3_open_v2(temporary,&destination,SQLITE_OPEN_READWRITE|SQLITE_OPEN_FULLMUTEX,NULL);
    if(rc!=SQLITE_OK){if(destination)sqlite3_close(destination);pthread_mutex_unlock(&s->mutex);unlink(temporary);free(temporary);free(parent);free(absolute);return map_sqlite(rc);}
    (void)sqlite3_busy_timeout(destination,5000);
    bool configured=exec_sql(destination,"PRAGMA foreign_keys=ON; PRAGMA trusted_schema=OFF; PRAGMA synchronous=FULL; PRAGMA journal_mode=DELETE;");
    sqlite3_backup *backup=configured?sqlite3_backup_init(destination,"main",s->db,"main"):NULL;
    if(!backup){sqlite3_close(destination);pthread_mutex_unlock(&s->mutex);unlink(temporary);free(temporary);free(parent);free(absolute);return CAPRI_SESSION_DATABASE;}
    unsigned attempts=0u,steps=0u;do{rc=sqlite3_backup_step(backup,256);if(rc==SQLITE_OK){if(++steps<100000u)continue;rc=SQLITE_BUSY;break;}if((rc==SQLITE_BUSY||rc==SQLITE_LOCKED)&&attempts++<500u){sqlite3_sleep(10);continue;}break;}while(true);
    int finish=sqlite3_backup_finish(backup);CapriSessionError result=(rc==SQLITE_DONE&&finish==SQLITE_OK)?validate_backup_snapshot(s,destination):map_sqlite(rc==SQLITE_DONE?finish:rc);
    int close_rc=sqlite3_close(destination);if(result==CAPRI_SESSION_OK&&close_rc!=SQLITE_OK)result=map_sqlite(close_rc);
    pthread_mutex_unlock(&s->mutex);
    if(result!=CAPRI_SESSION_OK){unlink(temporary);char sidecar[PATH_MAX+8u];(void)snprintf(sidecar,sizeof sidecar,"%s-journal",temporary);unlink(sidecar);(void)snprintf(sidecar,sizeof sidecar,"%s-wal",temporary);unlink(sidecar);(void)snprintf(sidecar,sizeof sidecar,"%s-shm",temporary);unlink(sidecar);free(temporary);free(parent);free(absolute);return result;}
    fd=open(temporary,O_RDONLY
#ifdef O_NOFOLLOW
      |O_NOFOLLOW
#endif
    );
    if(fd<0){result=CAPRI_SESSION_IO;}else{struct stat st;bool safe=fstat(fd,&st)==0&&S_ISREG(st.st_mode)&&st.st_uid==geteuid()&&st.st_nlink==1&&fchmod(fd,0600)==0&&fsync(fd)==0;close(fd);if(!safe)result=CAPRI_SESSION_IO;}
    bool published=false;
    if(result==CAPRI_SESSION_OK){if(link(temporary,absolute)==0){published=true;if(unlink(temporary)!=0)result=CAPRI_SESSION_IO;}else result=CAPRI_SESSION_IO;}
    if(result==CAPRI_SESSION_OK){int dirfd=open(parent,O_RDONLY
#ifdef O_DIRECTORY
      |O_DIRECTORY
#endif
    );if(dirfd<0||fsync(dirfd)!=0)result=CAPRI_SESSION_IO;if(dirfd>=0)close(dirfd);}
    if(!published){unlink(temporary);}else if(result!=CAPRI_SESSION_OK){/* Keep a published complete snapshot if only directory durability failed. */}
    free(temporary);free(parent);free(absolute);return result;
}
CapriSessionError capri_session_create_for_principal(CapriSessionStore *s,const char *principal,CapriSession *out) {
    if(!s||!out||!text_ok(principal,256u,true))return CAPRI_SESSION_INVALID;
    char id[37],now[32];if(!random_uuid(id)||!utc_now(now))return CAPRI_SESSION_IO;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
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
CapriSessionError capri_session_create(CapriSessionStore *s,CapriSession *out) {
    if(!s||!out)return CAPRI_SESSION_INVALID;
    char id[37],now[32];if(!random_uuid(id)||!utc_now(now))return CAPRI_SESSION_IO;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s))RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    char *empty_json=strdup("[]");if(!empty_json)RETURN_UNLOCK(s,CAPRI_SESSION_NO_MEMORY);
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"INSERT INTO sessions VALUES(?1,?2,?2,0,0,'[]')",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,now,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
    sqlite3_finalize(st);
    if(rc!=SQLITE_DONE){free(empty_json);RETURN_UNLOCK(s,map_sqlite(rc));}
    memset(out,0,sizeof *out);strcpy(out->session_id,id);strcpy(out->created_at,now);strcpy(out->updated_at,now);out->messages_json=empty_json;
    RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_get(CapriSessionStore *s,const char *id,CapriSession *out) {
    if(!s||!out||!text_ok(id,36u,true))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s))RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    CapriSessionError result=select_unowned(s,id,out);
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
static CapriSessionError commit_turn_internal(CapriSessionStore *s,const char *id,const char *principal,int64_t expected,const char *turn_json,const char *lease_owner,CapriSession *out) {
    if(!s||!out||!text_ok(id,36u,true)||(principal&&!text_ok(principal,256u,true))||expected<0)return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    size_t turn_count=0u;CapriSessionError e=validate_turn(s,turn_json,&turn_count);if(e!=CAPRI_SESSION_OK) RETURN_UNLOCK(s,e);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE")) RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    CapriSession current={0};e=principal?select_owned(s,id,principal,&current):select_unowned(s,id,&current);if(e!=CAPRI_SESSION_OK)goto fail;
    if(current.closed){e=CAPRI_SESSION_CLOSED;goto fail;}
    if(current.version!=expected){e=CAPRI_SESSION_CONFLICT;goto fail;}
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT owner_token,expires_at,(julianday(expires_at)>julianday('now')),(julianday(expires_at) IS NULL) FROM session_turn_leases WHERE session_id=?1",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}if(rc==SQLITE_ROW){const char *owner=(const char*)sqlite3_column_text(st,0);const unsigned char *expiry=sqlite3_column_text(st,1);if(!sqlite_text_ok(st,0,128u,true)||!sqlite_text_ok(st,1,64u,true)||!lease_timestamp_aware(expiry,sqlite3_column_bytes(st,1))||sqlite3_column_int(st,3)==1)e=CAPRI_SESSION_CORRUPT;else if(sqlite3_column_int(st,2)!=1||!lease_owner||strcmp(owner,lease_owner)!=0)e=CAPRI_SESSION_CONFLICT;}else if(rc!=SQLITE_DONE)e=map_sqlite(rc);else if(lease_owner)e=CAPRI_SESSION_CONFLICT;sqlite3_finalize(st);if(e!=CAPRI_SESSION_OK)goto fail;
    st=NULL;rc=sqlite3_prepare_v2(s->db,"SELECT json_array_length(?1), (SELECT count(*) FROM json_each(?1) WHERE json_extract(value,'$.role')='user')",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,current.messages_json,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}size_t old_count=rc==SQLITE_ROW?(size_t)sqlite3_column_int64(st,0):0u;size_t old_users=rc==SQLITE_ROW?(size_t)sqlite3_column_int64(st,1):0u;sqlite3_finalize(st);if(rc!=SQLITE_ROW){e=CAPRI_SESSION_CORRUPT;goto fail;}
    if(old_count+turn_count>s->max_messages){e=CAPRI_SESSION_LIMIT;goto fail;}
    if(old_users!=(size_t)current.version){e=CAPRI_SESSION_CORRUPT;goto fail;}
    st=NULL;const char *append_sql="SELECT json_group_array(json(value)) FROM (SELECT value,0 AS grp,CAST(key AS INTEGER) AS seq FROM json_each(?1) UNION ALL SELECT value,1 AS grp,CAST(key AS INTEGER) AS seq FROM json_each(?2) ORDER BY grp,seq)";
    rc=sqlite3_prepare_v2(s->db,append_sql,-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,current.messages_json,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,turn_json,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}char *combined=rc==SQLITE_ROW?strdup((const char*)sqlite3_column_text(st,0)):NULL;sqlite3_finalize(st);if(!combined){e=rc==SQLITE_ROW?CAPRI_SESSION_NO_MEMORY:CAPRI_SESSION_DATABASE;goto fail;}
    char now[32];if(!utc_now(now)){free(combined);e=CAPRI_SESSION_IO;goto fail;}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"UPDATE sessions SET updated_at=?1,version=version+1,messages_json=?2 WHERE session_id=?3 AND version=?4 AND closed=0",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,now,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,combined,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,id,-1,SQLITE_TRANSIENT);sqlite3_bind_int64(st,4,expected);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_DONE){free(combined);e=map_sqlite(rc);goto fail;}if(sqlite3_changes(s->db)!=1){free(combined);e=CAPRI_SESSION_CONFLICT;goto fail;}
    if(!exec_sql(s->db,"COMMIT")){free(combined);e=CAPRI_SESSION_DATABASE;goto fail;}
    *out=current; memset(&current,0,sizeof current); out->version=expected+1; strcpy(out->updated_at,now); free(out->messages_json); out->messages_json=combined;
    RETURN_UNLOCK(s,CAPRI_SESSION_OK);
fail:
    capri_session_free(&current);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,e);
}

CapriSessionError capri_session_commit_turn_for_principal(CapriSessionStore *s,const char *id,const char *principal,int64_t expected,const char *turn_json,const char *lease_owner,CapriSession *out) {
    if(!text_ok(principal,256u,true))return CAPRI_SESSION_INVALID;
    return commit_turn_internal(s,id,principal,expected,turn_json,lease_owner,out);
}
CapriSessionError capri_session_commit_turn(CapriSessionStore *s,const char *id,int64_t expected,const char *turn_json,const char *lease_owner,CapriSession *out) {
    return commit_turn_internal(s,id,NULL,expected,turn_json,lease_owner,out);
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
    st=NULL;rc=sqlite3_prepare_v2(s->db,"SELECT owner_token,expires_at,(julianday(expires_at)>julianday('now')),(julianday(expires_at) IS NULL) FROM session_turn_leases WHERE session_id=?1",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}if(rc==SQLITE_ROW){const char *old=(const char*)sqlite3_column_text(st,0);const unsigned char *old_expiry=sqlite3_column_text(st,1);int live=sqlite3_column_int(st,2);if(!sqlite_text_ok(st,0,128u,true)||!sqlite_text_ok(st,1,64u,true)||!lease_timestamp_aware(old_expiry,sqlite3_column_bytes(st,1))||sqlite3_column_int(st,3)==1){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CORRUPT);}if((live&&strcmp(old,token)!=0)||(!live&&strcmp(old,token)==0)){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CONFLICT);}sqlite3_finalize(st);st=NULL;rc=sqlite3_prepare_v2(s->db,"UPDATE session_turn_leases SET owner_token=?1,expires_at=?2 WHERE session_id=?3",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,token,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,expiry,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);}else if(rc==SQLITE_DONE){sqlite3_finalize(st);st=NULL;rc=sqlite3_prepare_v2(s->db,"INSERT INTO session_turn_leases VALUES(?1,?2,?3)",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,token,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,expiry,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);}else{sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}
    if(rc!=SQLITE_DONE){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_renew_turn_lease_for_principal(CapriSessionStore *s,const char *id,const char *principal,const char *token,double seconds) {
    if(!s||!lease_input(id,principal,token,seconds))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    char expiry[40];if(!lease_expiry(expiry,seconds)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE")) RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT 1 FROM session_owners WHERE session_id=?1 AND principal_id=?2",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,principal,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_ROW){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"SELECT owner_token,expires_at,(julianday(expires_at)>julianday('now')),(julianday(expires_at) IS NULL) FROM session_turn_leases WHERE session_id=?1",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}if(rc!=SQLITE_ROW){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_CONFLICT:map_sqlite(rc));}const unsigned char *owner_text=sqlite3_column_text(st,0);const unsigned char *current_expiry=sqlite3_column_text(st,1);int owner_bytes=sqlite3_column_bytes(st,0),live=sqlite3_column_int(st,2),invalid=sqlite3_column_int(st,3);char current_owner[129]={0};bool owner_valid=sqlite_text_ok(st,0,128u,true)&&owner_text&&owner_bytes>0&&owner_bytes<129;if(owner_valid)memcpy(current_owner,owner_text,(size_t)owner_bytes);bool aware=lease_timestamp_aware(current_expiry,sqlite3_column_bytes(st,1));sqlite3_finalize(st);if(!owner_valid||!current_expiry||!aware||invalid){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CORRUPT);}if(strcmp(current_owner,token)!=0||!live){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CONFLICT);}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"UPDATE session_turn_leases SET expires_at=?1 WHERE session_id=?2 AND owner_token=?3",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,expiry,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,token,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_DONE){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}if(sqlite3_changes(s->db)!=1){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CONFLICT);}if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_release_turn_lease_for_principal(CapriSessionStore *s,const char *id,const char *principal,const char *token,int *released) {
    if(!s||!text_ok(id,36u,true)||!text_ok(principal,256u,true)||!text_ok(token,128u,true)||!released) return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    *released=0;
    if(!exec_sql(s->db,"BEGIN IMMEDIATE")) RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT 1 FROM session_owners WHERE session_id=?1 AND principal_id=?2",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,principal,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_ROW){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"SELECT owner_token,expires_at,(julianday(expires_at)>julianday('now')),(julianday(expires_at) IS NULL) FROM session_turn_leases WHERE session_id=?1",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}if(rc==SQLITE_DONE){sqlite3_finalize(st);if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}RETURN_UNLOCK(s,CAPRI_SESSION_OK);}if(rc!=SQLITE_ROW){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}const unsigned char *owner_text=sqlite3_column_text(st,0);const unsigned char *current_expiry=sqlite3_column_text(st,1);int owner_bytes=sqlite3_column_bytes(st,0),live=sqlite3_column_int(st,2),invalid=sqlite3_column_int(st,3);char current_owner[129]={0};bool owner_valid=sqlite_text_ok(st,0,128u,true)&&owner_text&&owner_bytes>0&&owner_bytes<129;if(owner_valid)memcpy(current_owner,owner_text,(size_t)owner_bytes);bool aware=lease_timestamp_aware(current_expiry,sqlite3_column_bytes(st,1));sqlite3_finalize(st);if(!owner_valid||!current_expiry||!aware||invalid){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CORRUPT);}if(strcmp(current_owner,token)!=0||!live){if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}RETURN_UNLOCK(s,CAPRI_SESSION_OK);}st=NULL;rc=sqlite3_prepare_v2(s->db,"DELETE FROM session_turn_leases WHERE session_id=?1 AND owner_token=?2",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,token,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_DONE){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}*released=sqlite3_changes(s->db)==1;if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
static bool unowned_lease_input(const char *id,const char *token,double seconds) {
    return text_ok(id,36u,true)&&text_ok(token,128u,true)&&seconds>=3.0&&seconds<=3600.0;
}
CapriSessionError capri_session_claim_turn_lease(CapriSessionStore *s,const char *id,const char *token,double seconds) {
    if(!s||!unowned_lease_input(id,token,seconds))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s))RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    char expiry[40];if(!lease_expiry(expiry,seconds))RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE"))RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT closed FROM sessions s WHERE s.session_id=?1 AND NOT EXISTS(SELECT 1 FROM session_owners o WHERE o.session_id=s.session_id)",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
    if(rc!=SQLITE_ROW){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));}
    if(sqlite3_column_int(st,0)!=0){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CLOSED);}
    sqlite3_finalize(st);st=NULL;
    rc=sqlite3_prepare_v2(s->db,"SELECT owner_token,expires_at,(julianday(expires_at)>julianday('now')),(julianday(expires_at) IS NULL) FROM session_turn_leases WHERE session_id=?1",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
    if(rc==SQLITE_ROW){
        const unsigned char *old=sqlite3_column_text(st,0),*old_expiry=sqlite3_column_text(st,1);
        int live=sqlite3_column_int(st,2),invalid=sqlite3_column_int(st,3);
        if(!sqlite_text_ok(st,0,128u,true)||!sqlite_text_ok(st,1,64u,true)||!lease_timestamp_aware(old_expiry,sqlite3_column_bytes(st,1))||invalid){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CORRUPT);}
        if((live&&strcmp((const char*)old,token)!=0)||(!live&&strcmp((const char*)old,token)==0)){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CONFLICT);}
        sqlite3_finalize(st);st=NULL;
        rc=sqlite3_prepare_v2(s->db,"UPDATE session_turn_leases SET owner_token=?1,expires_at=?2 WHERE session_id=?3",-1,&st,NULL);
        if(rc==SQLITE_OK){sqlite3_bind_text(st,1,token,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,expiry,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
        sqlite3_finalize(st);
    } else if(rc==SQLITE_DONE){
        sqlite3_finalize(st);st=NULL;
        rc=sqlite3_prepare_v2(s->db,"INSERT INTO session_turn_leases VALUES(?1,?2,?3)",-1,&st,NULL);
        if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,token,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,expiry,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
        sqlite3_finalize(st);
    } else {sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}
    if(rc!=SQLITE_DONE){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}
    if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}
    RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_renew_turn_lease(CapriSessionStore *s,const char *id,const char *token,double seconds) {
    if(!s||!unowned_lease_input(id,token,seconds))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s))RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    char expiry[40];if(!lease_expiry(expiry,seconds))RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE"))RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT 1 FROM sessions s WHERE s.session_id=?1 AND NOT EXISTS(SELECT 1 FROM session_owners o WHERE o.session_id=s.session_id)",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
    sqlite3_finalize(st);
    if(rc!=SQLITE_ROW){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"SELECT owner_token,expires_at,(julianday(expires_at)>julianday('now')),(julianday(expires_at) IS NULL) FROM session_turn_leases WHERE session_id=?1",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
    if(rc!=SQLITE_ROW){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_CONFLICT:map_sqlite(rc));}
    const unsigned char *owner=sqlite3_column_text(st,0),*current_expiry=sqlite3_column_text(st,1);
    int owner_bytes=sqlite3_column_bytes(st,0),live=sqlite3_column_int(st,2),invalid=sqlite3_column_int(st,3);
    char current_owner[129]={0};bool owner_valid=sqlite_text_ok(st,0,128u,true)&&owner&&owner_bytes>0&&owner_bytes<129;
    if(owner_valid)memcpy(current_owner,owner,(size_t)owner_bytes);
    bool aware=lease_timestamp_aware(current_expiry,sqlite3_column_bytes(st,1));sqlite3_finalize(st);
    if(!owner_valid||!aware||invalid){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CORRUPT);}
    if(strcmp(current_owner,token)!=0||!live){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CONFLICT);}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"UPDATE session_turn_leases SET expires_at=?1 WHERE session_id=?2 AND owner_token=?3",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,expiry,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,3,token,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
    sqlite3_finalize(st);
    if(rc!=SQLITE_DONE){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}
    if(sqlite3_changes(s->db)!=1){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CONFLICT);}
    if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}
    RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_release_turn_lease(CapriSessionStore *s,const char *id,const char *token,int *released) {
    if(!s||!text_ok(id,36u,true)||!text_ok(token,128u,true)||!released)return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s))RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    *released=0;
    if(!exec_sql(s->db,"BEGIN IMMEDIATE"))RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"SELECT 1 FROM sessions s WHERE s.session_id=?1 AND NOT EXISTS(SELECT 1 FROM session_owners o WHERE o.session_id=s.session_id)",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
    sqlite3_finalize(st);
    if(rc!=SQLITE_ROW){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_NOT_FOUND:map_sqlite(rc));}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"SELECT owner_token,expires_at,(julianday(expires_at)>julianday('now')),(julianday(expires_at) IS NULL) FROM session_turn_leases WHERE session_id=?1",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
    if(rc==SQLITE_DONE){sqlite3_finalize(st);if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}RETURN_UNLOCK(s,CAPRI_SESSION_OK);}
    if(rc!=SQLITE_ROW){sqlite3_finalize(st);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}
    const unsigned char *owner=sqlite3_column_text(st,0),*current_expiry=sqlite3_column_text(st,1);
    int owner_bytes=sqlite3_column_bytes(st,0),live=sqlite3_column_int(st,2),invalid=sqlite3_column_int(st,3);
    char current_owner[129]={0};bool owner_valid=sqlite_text_ok(st,0,128u,true)&&owner&&owner_bytes>0&&owner_bytes<129;
    if(owner_valid)memcpy(current_owner,owner,(size_t)owner_bytes);
    bool aware=lease_timestamp_aware(current_expiry,sqlite3_column_bytes(st,1));sqlite3_finalize(st);
    if(!owner_valid||!aware||invalid){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_CORRUPT);}
    if(strcmp(current_owner,token)!=0||!live){if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}RETURN_UNLOCK(s,CAPRI_SESSION_OK);}
    st=NULL;rc=sqlite3_prepare_v2(s->db,"DELETE FROM session_turn_leases WHERE session_id=?1 AND owner_token=?2",-1,&st,NULL);
    if(rc==SQLITE_OK){sqlite3_bind_text(st,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,token,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
    sqlite3_finalize(st);
    if(rc!=SQLITE_DONE){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}
    *released=sqlite3_changes(s->db)==1;
    if(!exec_sql(s->db,"COMMIT")){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}
    RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_close(CapriSessionStore *s,const char *id,CapriSession *out) {
    if(!s||!out||!text_ok(id,36u,true))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s))RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE"))RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    CapriSession current={0};CapriSessionError e=select_unowned(s,id,&current);
    if(e!=CAPRI_SESSION_OK){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,e);}
    if(!current.closed){
        char now[32];if(!utc_now(now)){capri_session_free(&current);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_IO);}
        sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"UPDATE sessions SET closed=1,updated_at=?1 WHERE session_id=?2 AND NOT EXISTS(SELECT 1 FROM session_owners o WHERE o.session_id=sessions.session_id)",-1,&st,NULL);
        if(rc==SQLITE_OK){sqlite3_bind_text(st,1,now,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}
        sqlite3_finalize(st);if(rc!=SQLITE_DONE||sqlite3_changes(s->db)!=1){capri_session_free(&current);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,rc==SQLITE_DONE?CAPRI_SESSION_CONFLICT:map_sqlite(rc));}
        current.closed=1;strcpy(current.updated_at,now);
    }
    if(!exec_sql(s->db,"COMMIT")){capri_session_free(&current);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}
    *out=current;RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_close_for_principal(CapriSessionStore *s,const char *id,const char *principal,CapriSession *out) {
    if(!s||!out||!text_ok(id,36u,true)||!text_ok(principal,256u,true))return CAPRI_SESSION_INVALID;
    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)) RETURN_UNLOCK(s,CAPRI_SESSION_IO);
    if(!exec_sql(s->db,"BEGIN IMMEDIATE")) RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);
    CapriSession current={0};CapriSessionError e=select_owned(s,id,principal,&current);if(e!=CAPRI_SESSION_OK){exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,e);}
    if(!current.closed){char now[32];if(!utc_now(now)){capri_session_free(&current);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_IO);}sqlite3_stmt *st=NULL;int rc=sqlite3_prepare_v2(s->db,"UPDATE sessions SET closed=1,updated_at=?1 WHERE session_id=?2",-1,&st,NULL);if(rc==SQLITE_OK){sqlite3_bind_text(st,1,now,-1,SQLITE_TRANSIENT);sqlite3_bind_text(st,2,id,-1,SQLITE_TRANSIENT);rc=sqlite3_step(st);}sqlite3_finalize(st);if(rc!=SQLITE_DONE){capri_session_free(&current);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,map_sqlite(rc));}current.closed=1;strcpy(current.updated_at,now);}
    if(!exec_sql(s->db,"COMMIT")){capri_session_free(&current);exec_sql(s->db,"ROLLBACK");RETURN_UNLOCK(s,CAPRI_SESSION_DATABASE);}*out=current;RETURN_UNLOCK(s,CAPRI_SESSION_OK);
}
CapriSessionError capri_session_restore_to(CapriSessionStore *s,const char *backup_path,const char *destination_path) {
    if(!s||!text_ok(backup_path,PATH_MAX-1u,true)||!text_ok(destination_path,PATH_MAX-1u,true))return CAPRI_SESSION_INVALID;
    char *source_path=NULL,*target_path=NULL;
    if(!safe_path(backup_path,&source_path))return CAPRI_SESSION_IO;
    if(!safe_path(destination_path,&target_path)){free(source_path);return CAPRI_SESSION_IO;}
    if(strcmp(source_path,target_path)==0||strcmp(source_path,s->path)==0||strcmp(target_path,s->path)==0){free(source_path);free(target_path);return CAPRI_SESSION_INVALID;}
    struct stat target_stat;
    if(lstat(target_path,&target_stat)==0){free(source_path);free(target_path);return CAPRI_SESSION_INVALID;}
    if(errno!=ENOENT){free(source_path);free(target_path);return CAPRI_SESSION_IO;}
    char *slash=strrchr(target_path,'/');
    if(!slash){free(source_path);free(target_path);return CAPRI_SESSION_INVALID;}
    size_t parent_len=(size_t)(slash-target_path);
    char *parent=malloc(parent_len+1u);
    if(!parent){free(source_path);free(target_path);return CAPRI_SESSION_NO_MEMORY;}
    memcpy(parent,target_path,parent_len);parent[parent_len]='\0';
    size_t template_len=strlen(parent)+32u;
    if(template_len>PATH_MAX){free(parent);free(source_path);free(target_path);return CAPRI_SESSION_INVALID;}
    char *temporary=malloc(template_len);
    if(!temporary){free(parent);free(source_path);free(target_path);return CAPRI_SESSION_NO_MEMORY;}
    (void)snprintf(temporary,template_len,"%s/.capri-session-restore-XXXXXX",parent);
    int temp_fd=mkstemp(temporary);
    if(temp_fd<0){free(temporary);free(parent);free(source_path);free(target_path);return CAPRI_SESSION_IO;}
    bool temp_ok=fchmod(temp_fd,0600)==0&&fsync(temp_fd)==0;
    close(temp_fd);
    if(!temp_ok){unlink(temporary);free(temporary);free(parent);free(source_path);free(target_path);return CAPRI_SESSION_IO;}

    pthread_mutex_lock(&s->mutex);
    if(!store_path_safe(s)){pthread_mutex_unlock(&s->mutex);unlink(temporary);free(temporary);free(parent);free(source_path);free(target_path);return CAPRI_SESSION_IO;}
    int source_fd=open(source_path,O_RDONLY
#ifdef O_NOFOLLOW
      |O_NOFOLLOW
#endif
    );
    struct stat opened_source,path_source;
    bool source_safe=source_fd>=0&&fstat(source_fd,&opened_source)==0&&S_ISREG(opened_source.st_mode)&&opened_source.st_uid==geteuid()&&opened_source.st_nlink==1&&(opened_source.st_mode&0777u)==0600u&&lstat(source_path,&path_source)==0&&opened_source.st_dev==path_source.st_dev&&opened_source.st_ino==path_source.st_ino;
    if(!source_safe){if(source_fd>=0)close(source_fd);pthread_mutex_unlock(&s->mutex);unlink(temporary);free(temporary);free(parent);free(source_path);free(target_path);return CAPRI_SESSION_IO;}
    sqlite3 *source=NULL,*destination=NULL;
    int rc=sqlite3_open_v2(source_path,&source,SQLITE_OPEN_READONLY|SQLITE_OPEN_FULLMUTEX,NULL);
    struct stat after_open;
    if(rc==SQLITE_OK&&lstat(source_path,&after_open)==0&&opened_source.st_dev==after_open.st_dev&&opened_source.st_ino==after_open.st_ino){
        (void)sqlite3_busy_timeout(source,5000);
        (void)sqlite3_db_config(source,SQLITE_DBCONFIG_DEFENSIVE,1,NULL);
        (void)exec_sql(source,"PRAGMA query_only=ON; PRAGMA foreign_keys=ON; PRAGMA trusted_schema=OFF;");
    } else if(rc==SQLITE_OK)rc=SQLITE_CANTOPEN;
    CapriSessionError result=rc==SQLITE_OK?validate_backup_snapshot(s,source):map_sqlite(rc);
    if(result==CAPRI_SESSION_OK){
        rc=sqlite3_open_v2(temporary,&destination,SQLITE_OPEN_READWRITE|SQLITE_OPEN_FULLMUTEX,NULL);
        if(rc==SQLITE_OK){
            (void)sqlite3_busy_timeout(destination,5000);
            if(!exec_sql(destination,"PRAGMA foreign_keys=ON; PRAGMA trusted_schema=OFF; PRAGMA synchronous=FULL; PRAGMA journal_mode=DELETE;"))result=CAPRI_SESSION_DATABASE;
        } else result=map_sqlite(rc);
    }
    if(result==CAPRI_SESSION_OK){
        sqlite3_backup *backup=sqlite3_backup_init(destination,"main",source,"main");
        if(!backup)result=CAPRI_SESSION_DATABASE;
        else {
            unsigned attempts=0u,steps=0u;
            do {
                rc=sqlite3_backup_step(backup,256);
                if(rc==SQLITE_OK){if(++steps<100000u)continue;rc=SQLITE_BUSY;break;}
                if((rc==SQLITE_BUSY||rc==SQLITE_LOCKED)&&attempts++<500u){sqlite3_sleep(10);continue;}
                break;
            } while(true);
            int finish=sqlite3_backup_finish(backup);
            if(rc!=SQLITE_DONE||finish!=SQLITE_OK)result=map_sqlite(rc==SQLITE_DONE?finish:rc);
        }
    }
    if(result==CAPRI_SESSION_OK)result=validate_backup_snapshot(s,destination);
    if(destination){int close_rc=sqlite3_close(destination);if(result==CAPRI_SESSION_OK&&close_rc!=SQLITE_OK)result=map_sqlite(close_rc);}
    if(source){int close_rc=sqlite3_close(source);if(result==CAPRI_SESSION_OK&&close_rc!=SQLITE_OK)result=map_sqlite(close_rc);}
    close(source_fd);
    pthread_mutex_unlock(&s->mutex);
    if(result!=CAPRI_SESSION_OK){
        unlink(temporary);char sidecar[PATH_MAX+8u];
        (void)snprintf(sidecar,sizeof sidecar,"%s-journal",temporary);unlink(sidecar);
        (void)snprintf(sidecar,sizeof sidecar,"%s-wal",temporary);unlink(sidecar);
        (void)snprintf(sidecar,sizeof sidecar,"%s-shm",temporary);unlink(sidecar);
        free(temporary);free(parent);free(source_path);free(target_path);return result;
    }
    temp_fd=open(temporary,O_RDONLY
#ifdef O_NOFOLLOW
      |O_NOFOLLOW
#endif
    );
    if(temp_fd<0)result=CAPRI_SESSION_IO;
    else {
        struct stat st;
        bool safe=fstat(temp_fd,&st)==0&&S_ISREG(st.st_mode)&&st.st_uid==geteuid()&&st.st_nlink==1&&(st.st_mode&0777u)==0600u&&fsync(temp_fd)==0;
        close(temp_fd);if(!safe)result=CAPRI_SESSION_IO;
    }
    bool published=false;
    if(result==CAPRI_SESSION_OK){if(link(temporary,target_path)==0){published=true;if(unlink(temporary)!=0)result=CAPRI_SESSION_IO;}else result=CAPRI_SESSION_IO;}
    if(result==CAPRI_SESSION_OK){
        int dirfd=open(parent,O_RDONLY
#ifdef O_DIRECTORY
          |O_DIRECTORY
#endif
        );
        if(dirfd<0||fsync(dirfd)!=0)result=CAPRI_SESSION_IO;
        if(dirfd>=0)close(dirfd);
    }
    if(!published)unlink(temporary);
    free(temporary);free(parent);free(source_path);free(target_path);
    return result;
}
const char *capri_session_error_string(CapriSessionError e){static const char *const m[]={"ok","invalid input","filesystem operation failed","SQLite operation failed","session not found","session closed","session conflict","resource limit reached","persisted session is corrupt","out of memory"};return e>=CAPRI_SESSION_OK&&e<=CAPRI_SESSION_NO_MEMORY?m[e]:"unknown session error";}
