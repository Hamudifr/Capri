#define _POSIX_C_SOURCE 200809L
#include "capri_session_store.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <sqlite3.h>
#include <pthread.h>
#include <sys/wait.h>
#include <time.h>

static int write_all(int fd,const void *buffer,size_t size) {
    const unsigned char *cursor=(const unsigned char*)buffer;
    while(size>0u){
        ssize_t written=write(fd,cursor,size);
        if(written<0&&errno==EINTR)continue;
        if(written<=0)return 0;
        cursor+=(size_t)written;
        size-=(size_t)written;
    }
    return 1;
}

typedef struct {
    CapriSessionStore *store;
    const char *session_id;
    pthread_barrier_t *barrier;
    CapriSessionError result;
    CapriSession output;
} CommitThread;
static void *concurrent_commit(void *opaque) {
    CommitThread *arg=(CommitThread*)opaque;
    const char *turn="[{\"role\":\"user\",\"content\":\"race\"},{\"role\":\"assistant\",\"content\":\"winner\"}]";
    (void)pthread_barrier_wait(arg->barrier);
    arg->result=capri_session_commit_turn_for_principal(arg->store,arg->session_id,"principal-race",0,turn,NULL,&arg->output);
    return NULL;
}

int main(void) {
    char dir[]="/tmp/capri-c-test-XXXXXX"; assert(mkdtemp(dir)!=NULL); assert(chmod(dir,0700)==0);
    char path[512]; snprintf(path,sizeof path,"%s/sessions.sqlite3",dir);
    char backup_path[512]; snprintf(backup_path,sizeof backup_path,"%s/sessions-backup.sqlite3",dir);
    char restored_path[512]; snprintf(restored_path,sizeof restored_path,"%s/sessions-restored.sqlite3",dir);
    char corrupt_backup_path[512]; snprintf(corrupt_backup_path,sizeof corrupt_backup_path,"%s/corrupt-backup.sqlite3",dir);
    char corrupt_restore_path[512]; snprintf(corrupt_restore_path,sizeof corrupt_restore_path,"%s/corrupt-restored.sqlite3",dir);
    CapriSessionError error;
    char unsafe_dir[]="/tmp/capri-c-insecure-XXXXXX";
    assert(mkdtemp(unsafe_dir)!=NULL);
    assert(chmod(unsafe_dir,0755)==0);
    char unsafe_path[512]; snprintf(unsafe_path,sizeof unsafe_path,"%s/sessions.sqlite3",unsafe_dir);
    assert(capri_session_store_open(unsafe_path,200,16000,64000,131072,&error)==NULL);
    assert(chmod(unsafe_dir,0700)==0);
    assert(rmdir(unsafe_dir)==0);
    CapriSessionStore *store=capri_session_store_open(path,200,16000,64000,131072,&error);
    assert(store!=NULL && error==CAPRI_SESSION_OK);
    CapriSession alice={0}, bob={0}, committed={0};
    assert(capri_session_create_for_principal(store,"principal-alice",&alice)==CAPRI_SESSION_OK);
    /* Python bounds principal IDs and lease tokens by Unicode characters, not UTF-8 bytes. */
    char unicode_principal[401]={0},unicode_token[401]={0};
    for(size_t unicode_index=0u;unicode_index<100u;++unicode_index){
        memcpy(unicode_principal+unicode_index*4u,"\xF0\x9F\xA7\xAA",4u);
        memcpy(unicode_token+unicode_index*4u,"\xF0\x9F\x94\x90",4u);
    }
    CapriSession unicode_session={0},unicode_committed={0};
    assert(capri_session_create_for_principal(store,unicode_principal,&unicode_session)==CAPRI_SESSION_OK);
    assert(capri_session_claim_turn_lease_for_principal(store,unicode_session.session_id,unicode_principal,unicode_token,30.0)==CAPRI_SESSION_OK);
    const char *unicode_turn="[{\"role\":\"user\",\"content\":\"unicode principal\"},{\"role\":\"assistant\",\"content\":\"unicode lease token\"}]";
    assert(capri_session_commit_turn_for_principal(store,unicode_session.session_id,unicode_principal,0,unicode_turn,unicode_token,&unicode_committed)==CAPRI_SESSION_OK);
    assert(unicode_committed.version==1);
    int unicode_released=0;
    assert(capri_session_release_turn_lease_for_principal(store,unicode_session.session_id,unicode_principal,unicode_token,&unicode_released)==CAPRI_SESSION_OK&&unicode_released==1);
    assert(capri_session_integrity_check(store)==CAPRI_SESSION_OK);
    capri_session_free(&unicode_session);capri_session_free(&unicode_committed);
    assert(alice.version==0 && !alice.closed && strcmp(alice.messages_json,"[]")==0);
    CapriSession legacy={0},legacy_read={0},legacy_committed={0},legacy_closed={0};
    assert(capri_session_create(store,&legacy)==CAPRI_SESSION_OK);
    assert(capri_session_get(store,legacy.session_id,&legacy_read)==CAPRI_SESSION_OK);
    assert(capri_session_get_for_principal(store,legacy.session_id,"principal-alice",&bob)==CAPRI_SESSION_NOT_FOUND);
    assert(capri_session_get(store,alice.session_id,&bob)==CAPRI_SESSION_NOT_FOUND);
    const char *unowned_bypass_turn="[{\"role\":\"user\",\"content\":\"bypass attempt\"},{\"role\":\"assistant\",\"content\":\"must remain blocked\"}]";
    int unowned_bypass_released=0;
    assert(capri_session_commit_turn(store,alice.session_id,0,unowned_bypass_turn,NULL,&bob)==CAPRI_SESSION_NOT_FOUND);
    assert(capri_session_close(store,alice.session_id,&bob)==CAPRI_SESSION_NOT_FOUND);
    assert(capri_session_claim_turn_lease(store,alice.session_id,"legacy-worker",30.0)==CAPRI_SESSION_NOT_FOUND);
    assert(capri_session_renew_turn_lease(store,alice.session_id,"legacy-worker",30.0)==CAPRI_SESSION_NOT_FOUND);
    assert(capri_session_release_turn_lease(store,alice.session_id,"legacy-worker",&unowned_bypass_released)==CAPRI_SESSION_NOT_FOUND&&unowned_bypass_released==0);
    const char *legacy_turn="[{\"role\":\"user\",\"content\":\"legacy\"},{\"role\":\"assistant\",\"content\":\"compatible\"}]";
    assert(capri_session_claim_turn_lease(store,legacy.session_id,"legacy-worker",30.0)==CAPRI_SESSION_OK);
    assert(capri_session_renew_turn_lease(store,legacy.session_id,"legacy-worker",30.0)==CAPRI_SESSION_OK);
    assert(capri_session_claim_turn_lease_for_principal(store,legacy.session_id,"principal-alice","other-worker",30.0)==CAPRI_SESSION_NOT_FOUND);
    assert(capri_session_commit_turn(store,legacy.session_id,0,legacy_turn,"wrong-worker",&legacy_committed)==CAPRI_SESSION_CONFLICT);
    assert(capri_session_commit_turn(store,legacy.session_id,0,legacy_turn,"legacy-worker",&legacy_committed)==CAPRI_SESSION_OK);
    assert(legacy_committed.version==1);
    int legacy_released=0;
    assert(capri_session_release_turn_lease(store,legacy.session_id,"legacy-worker",&legacy_released)==CAPRI_SESSION_OK&&legacy_released==1);
    assert(capri_session_close(store,legacy.session_id,&legacy_closed)==CAPRI_SESSION_OK&&legacy_closed.closed);
    assert(capri_session_commit_turn(store,legacy.session_id,1,legacy_turn,NULL,&bob)==CAPRI_SESSION_CLOSED);
    capri_session_free(&legacy);capri_session_free(&legacy_read);capri_session_free(&legacy_committed);capri_session_free(&legacy_closed);
    char session_id[37]; strcpy(session_id,alice.session_id);
    assert(capri_session_get_for_principal(store,alice.session_id,"principal-bob",&bob)==CAPRI_SESSION_NOT_FOUND);
    const char *turn="[{\"role\":\"user\",\"content\":\"hello\"},{\"role\":\"assistant\",\"content\":\"world\"}]";
    assert(capri_session_commit_turn_for_principal(store,session_id,"principal-bob",0,turn,NULL,&committed)==CAPRI_SESSION_NOT_FOUND);
    assert(capri_session_commit_turn_for_principal(store,alice.session_id,"principal-alice",0,turn,NULL,&committed)==CAPRI_SESSION_OK);
    assert(committed.version==1 && strstr(committed.messages_json,"hello")!=NULL);
    CapriSession stale={0};
    assert(capri_session_commit_turn_for_principal(store,session_id,"principal-alice",0,turn,NULL,&stale)==CAPRI_SESSION_CONFLICT);
    const char *bad="[{\"role\":\"assistant\",\"content\":\"no user\"}]";
    assert(capri_session_commit_turn_for_principal(store,session_id,"principal-alice",1,bad,NULL,&stale)==CAPRI_SESSION_INVALID);
    const char *unicode_blank="[{\"role\":\"user\",\"content\":\"\\u00a0\"},{\"role\":\"assistant\",\"content\":\"reply\"}]";
    assert(capri_session_commit_turn_for_principal(store,session_id,"principal-alice",1,unicode_blank,NULL,&stale)==CAPRI_SESSION_INVALID);
    const char *python_strip_control_blank="[{\"role\":\"user\",\"content\":\"\\u001c\"},{\"role\":\"assistant\",\"content\":\"reply\"}]";
    assert(capri_session_commit_turn_for_principal(store,session_id,"principal-alice",1,python_strip_control_blank,NULL,&stale)==CAPRI_SESSION_INVALID);
    const char *wrong_json_type="[{\"role\":\"user\",\"content\":123},{\"role\":\"assistant\",\"content\":\"reply\"}]";
    assert(capri_session_commit_turn_for_principal(store,session_id,"principal-alice",1,wrong_json_type,NULL,&stale)==CAPRI_SESSION_INVALID);
    assert(capri_session_claim_turn_lease_for_principal(store,session_id,"principal-alice","worker-a",30.0)==CAPRI_SESSION_OK);
    assert(capri_session_claim_turn_lease_for_principal(store,session_id,"principal-alice","worker-b",30.0)==CAPRI_SESSION_CONFLICT);
    assert(capri_session_renew_turn_lease_for_principal(store,session_id,"principal-bob","worker-a",30.0)==CAPRI_SESSION_NOT_FOUND);
    const char *turn2="[{\"role\":\"user\",\"content\":\"second\"},{\"role\":\"assistant\",\"content\":\"reply\"}]";
    assert(capri_session_commit_turn_for_principal(store,session_id,"principal-alice",1,turn2,"worker-b",&stale)==CAPRI_SESSION_CONFLICT);
    assert(capri_session_commit_turn_for_principal(store,session_id,"principal-alice",1,turn2,"worker-a",&stale)==CAPRI_SESSION_OK);
    assert(stale.version==2 && strstr(stale.messages_json,"second")!=NULL);
    int released=0; assert(capri_session_release_turn_lease_for_principal(store,session_id,"principal-alice","worker-a",&released)==CAPRI_SESSION_OK && released==1);
    assert(capri_session_renew_turn_lease_for_principal(store,session_id,"principal-alice","worker-a",30.0)==CAPRI_SESSION_CONFLICT);
    assert(capri_session_close_for_principal(store,session_id,"principal-alice",&bob)==CAPRI_SESSION_OK && bob.closed);
    assert(capri_session_commit_turn_for_principal(store,session_id,"principal-alice",2,turn,NULL,&committed)==CAPRI_SESSION_CLOSED);
    capri_session_free(&alice); capri_session_free(&committed); capri_session_free(&stale); capri_session_free(&bob); capri_session_store_close(store);
    store=capri_session_store_open(path,200,16000,64000,131072,&error); assert(store!=NULL);
    assert(capri_session_get_for_principal(store,session_id,"principal-alice",&bob)==CAPRI_SESSION_OK);
    assert(bob.version==2 && bob.closed); capri_session_free(&bob);
    sqlite3 *raw=NULL; assert(sqlite3_open(path,&raw)==SQLITE_OK);
    assert(sqlite3_exec(raw,"UPDATE session_owners SET principal_id='principal-bob'",NULL,NULL,NULL)!=SQLITE_OK);
    sqlite3_close(raw);
    CapriSession race_session={0};
    assert(capri_session_create_for_principal(store,"principal-race",&race_session)==CAPRI_SESSION_OK);
    CapriSessionStore *store2=capri_session_store_open(path,200,16000,64000,131072,&error); assert(store2!=NULL);
    pthread_barrier_t barrier; assert(pthread_barrier_init(&barrier,NULL,2)==0);
    CommitThread a={.store=store,.session_id=race_session.session_id,.barrier=&barrier};
    CommitThread b={.store=store2,.session_id=race_session.session_id,.barrier=&barrier};
    pthread_t ta,tb; assert(pthread_create(&ta,NULL,concurrent_commit,&a)==0); assert(pthread_create(&tb,NULL,concurrent_commit,&b)==0);
    pthread_join(ta,NULL); pthread_join(tb,NULL); pthread_barrier_destroy(&barrier);
    assert((a.result==CAPRI_SESSION_OK&&b.result==CAPRI_SESSION_CONFLICT)||(b.result==CAPRI_SESSION_OK&&a.result==CAPRI_SESSION_CONFLICT));
    capri_session_free(&a.output); capri_session_free(&b.output); capri_session_store_close(store2);
    CapriSession process_session={0};
    assert(capri_session_create_for_principal(store,"principal-race",&process_session)==CAPRI_SESSION_OK);
    int ready_pipe[2],start_pipe[2],process_result_pipe[2];
    assert(pipe(ready_pipe)==0&&pipe(start_pipe)==0&&pipe(process_result_pipe)==0);
    pid_t worker=fork();assert(worker>=0);
    if(worker==0){
        close(ready_pipe[0]);close(start_pipe[1]);close(process_result_pipe[0]);
        CapriSessionError child_error=CAPRI_SESSION_INVALID;
        CapriSessionStore *child_store=capri_session_store_open(path,200,16000,64000,131072,&child_error);
        int ready=child_store!=NULL&&child_error==CAPRI_SESSION_OK;
        if(!write_all(ready_pipe[1],&ready,sizeof ready)){close(ready_pipe[1]);_exit(4);}close(ready_pipe[1]);
        if(!ready){close(start_pipe[0]);close(process_result_pipe[1]);_exit(2);}
        unsigned char go=0;if(read(start_pipe[0],&go,sizeof go)!=(ssize_t)sizeof go){capri_session_store_close(child_store);_exit(3);}
        close(start_pipe[0]);
        const char *process_turn="[{\"role\":\"user\",\"content\":\"process race\"},{\"role\":\"assistant\",\"content\":\"child\"}]";
        CapriSession child_output={0};
        CapriSessionError child_result=capri_session_commit_turn_for_principal(child_store,process_session.session_id,"principal-race",0,process_turn,NULL,&child_output);
        int child_code=(int)child_result;
        if(!write_all(process_result_pipe[1],&child_code,sizeof child_code)){capri_session_free(&child_output);capri_session_store_close(child_store);close(process_result_pipe[1]);_exit(5);}
        capri_session_free(&child_output);capri_session_store_close(child_store);close(process_result_pipe[1]);_exit(0);
    }
    close(ready_pipe[1]);close(start_pipe[0]);close(process_result_pipe[1]);
    int child_ready=0;assert(read(ready_pipe[0],&child_ready,sizeof child_ready)==(ssize_t)sizeof child_ready);close(ready_pipe[0]);assert(child_ready==1);
    unsigned char go=1;assert(write(start_pipe[1],&go,sizeof go)==(ssize_t)sizeof go);close(start_pipe[1]);
    const char *process_turn="[{\"role\":\"user\",\"content\":\"process race\"},{\"role\":\"assistant\",\"content\":\"parent\"}]";
    CapriSession parent_output={0};
    CapriSessionError parent_result=capri_session_commit_turn_for_principal(store,process_session.session_id,"principal-race",0,process_turn,NULL,&parent_output);
    int child_result_code=-1;assert(read(process_result_pipe[0],&child_result_code,sizeof child_result_code)==(ssize_t)sizeof child_result_code);close(process_result_pipe[0]);
    int worker_status=0;assert(waitpid(worker,&worker_status,0)==worker);assert(WIFEXITED(worker_status)&&WEXITSTATUS(worker_status)==0);
    CapriSessionError child_result=(CapriSessionError)child_result_code;
    assert((parent_result==CAPRI_SESSION_OK&&child_result==CAPRI_SESSION_CONFLICT)||(child_result==CAPRI_SESSION_OK&&parent_result==CAPRI_SESSION_CONFLICT));
    CapriSession process_state={0};assert(capri_session_get_for_principal(store,process_session.session_id,"principal-race",&process_state)==CAPRI_SESSION_OK&&process_state.version==1);
    capri_session_free(&process_state);capri_session_free(&parent_output);capri_session_free(&process_session);
    CapriSession race_state={0};
    assert(capri_session_get_for_principal(store,race_session.session_id,"principal-race",&race_state)==CAPRI_SESSION_OK);
    assert(race_state.version==1);
    assert(capri_session_claim_turn_lease_for_principal(store,race_session.session_id,"principal-race","backup-worker",30.0)==CAPRI_SESSION_OK);
    size_t large_len=64000u;const char *large_prefix="[{\"role\":\"user\",\"content\":\"x\"},{\"role\":\"assistant\",\"content\":\"";const char *large_suffix="\"}]";
    size_t turn_size=strlen(large_prefix)+large_len+strlen(large_suffix)+1u;char *large_turn=malloc(turn_size);assert(large_turn!=NULL);
    strcpy(large_turn,large_prefix);memset(large_turn+strlen(large_prefix),'x',large_len);strcpy(large_turn+strlen(large_prefix)+large_len,large_suffix);
    for(int k=0;k<20;++k){CapriSession large_session={0},large_committed={0};assert(capri_session_create_for_principal(store,"principal-large",&large_session)==CAPRI_SESSION_OK);assert(capri_session_commit_turn_for_principal(store,large_session.session_id,"principal-large",0,large_turn,NULL,&large_committed)==CAPRI_SESSION_OK);capri_session_free(&large_session);capri_session_free(&large_committed);}
    free(large_turn);
    assert(capri_session_integrity_check(store)==CAPRI_SESSION_OK);
    assert(capri_session_backup_to(store,path)==CAPRI_SESSION_INVALID);
    assert(capri_session_backup_to(store,backup_path)==CAPRI_SESSION_OK);
    assert(capri_session_backup_to(store,backup_path)==CAPRI_SESSION_INVALID);
    assert(capri_session_restore_to(store,backup_path,backup_path)==CAPRI_SESSION_INVALID);
    assert(capri_session_restore_to(store,backup_path,path)==CAPRI_SESSION_INVALID);
    assert(capri_session_restore_to(store,backup_path,restored_path)==CAPRI_SESSION_OK);
    assert(capri_session_restore_to(store,backup_path,restored_path)==CAPRI_SESSION_INVALID);
    CapriSessionStore *backup_store=capri_session_store_open(restored_path,200,16000,64000,131072,&error); assert(backup_store!=NULL);
    CapriSession backup_session={0};
    assert(capri_session_get_for_principal(backup_store,session_id,"principal-alice",&backup_session)==CAPRI_SESSION_OK);
    assert(backup_session.version==2 && backup_session.closed);
    assert(capri_session_integrity_check(backup_store)==CAPRI_SESSION_OK);
    const char *backup_turn="[{\"role\":\"user\",\"content\":\"backup\"},{\"role\":\"assistant\",\"content\":\"restored lease works\"}]";
    CapriSession backup_race={0};
    assert(capri_session_commit_turn_for_principal(backup_store,race_session.session_id,"principal-race",1,backup_turn,"backup-worker",&backup_race)==CAPRI_SESSION_OK);
    assert(backup_race.version==2);
    capri_session_free(&backup_race); capri_session_free(&backup_session); capri_session_store_close(backup_store);
    int backup_lease_released=0;
    assert(capri_session_release_turn_lease_for_principal(store,race_session.session_id,"principal-race","backup-worker",&backup_lease_released)==CAPRI_SESSION_OK&&backup_lease_released==1);
    capri_session_free(&race_session); capri_session_free(&race_state);
    CapriSession corrupt_session={0};
    assert(sqlite3_open(path,&raw)==SQLITE_OK);
    assert(capri_session_create_for_principal(store,"principal-corrupt",&corrupt_session)==CAPRI_SESSION_OK);
    sqlite3_stmt *lease_insert=NULL;
    assert(sqlite3_prepare_v2(raw,"INSERT INTO session_turn_leases(session_id,owner_token,expires_at) VALUES(?1,'worker-corrupt','not-a-date')",-1,&lease_insert,NULL)==SQLITE_OK);
    sqlite3_bind_text(lease_insert,1,corrupt_session.session_id,-1,SQLITE_TRANSIENT);
    assert(sqlite3_step(lease_insert)==SQLITE_DONE); sqlite3_finalize(lease_insert);
    assert(capri_session_claim_turn_lease_for_principal(store,corrupt_session.session_id,"principal-corrupt","worker-new",30.0)==CAPRI_SESSION_CORRUPT);
    assert(capri_session_renew_turn_lease_for_principal(store,corrupt_session.session_id,"principal-corrupt","worker-corrupt",30.0)==CAPRI_SESSION_CORRUPT);
    assert(capri_session_release_turn_lease_for_principal(store,corrupt_session.session_id,"principal-corrupt","worker-corrupt",&released)==CAPRI_SESSION_CORRUPT);
    assert(capri_session_commit_turn_for_principal(store,corrupt_session.session_id,"principal-corrupt",0,turn,NULL,&committed)==CAPRI_SESSION_CORRUPT);
    assert(capri_session_integrity_check(store)==CAPRI_SESSION_CORRUPT);
    assert(capri_session_backup_to(store,corrupt_backup_path)==CAPRI_SESSION_CORRUPT);
    struct stat missing_backup; assert(lstat(corrupt_backup_path,&missing_backup)!=0);
    sqlite3 *corrupt_copy=NULL; assert(sqlite3_open(corrupt_backup_path,&corrupt_copy)==SQLITE_OK);
    assert(chmod(corrupt_backup_path,0600)==0);
    sqlite3_backup *copy_backup=sqlite3_backup_init(corrupt_copy,"main",raw,"main"); assert(copy_backup!=NULL);
    int copy_rc; do { copy_rc=sqlite3_backup_step(copy_backup,256); } while(copy_rc==SQLITE_OK);
    assert(copy_rc==SQLITE_DONE); assert(sqlite3_backup_finish(copy_backup)==SQLITE_OK); assert(sqlite3_close(corrupt_copy)==SQLITE_OK);
    assert(capri_session_restore_to(store,corrupt_backup_path,corrupt_restore_path)==CAPRI_SESSION_CORRUPT);
    struct stat missing_restore; assert(lstat(corrupt_restore_path,&missing_restore)!=0);
    capri_session_free(&corrupt_session); capri_session_free(&committed);
    CapriSession nul_owner_session={0};
    assert(capri_session_create_for_principal(store,"principal-nul-owner",&nul_owner_session)==CAPRI_SESSION_OK);
    sqlite3_stmt *nul_insert=NULL;
    assert(sqlite3_prepare_v2(raw,"INSERT INTO session_turn_leases(session_id,owner_token,expires_at) VALUES(?1,CAST('worker-corrupt' || char(0) || 'tail' AS TEXT),'2099-01-01T00:00:00Z')",-1,&nul_insert,NULL)==SQLITE_OK);
    sqlite3_bind_text(nul_insert,1,nul_owner_session.session_id,-1,SQLITE_TRANSIENT);
    assert(sqlite3_step(nul_insert)==SQLITE_DONE); sqlite3_finalize(nul_insert);
    assert(capri_session_claim_turn_lease_for_principal(store,nul_owner_session.session_id,"principal-nul-owner","worker-new",30.0)==CAPRI_SESSION_CORRUPT);
    assert(capri_session_renew_turn_lease_for_principal(store,nul_owner_session.session_id,"principal-nul-owner","worker-corrupt",30.0)==CAPRI_SESSION_CORRUPT);
    assert(capri_session_release_turn_lease_for_principal(store,nul_owner_session.session_id,"principal-nul-owner","worker-corrupt",&released)==CAPRI_SESSION_CORRUPT);
    assert(capri_session_commit_turn_for_principal(store,nul_owner_session.session_id,"principal-nul-owner",0,turn,NULL,&committed)==CAPRI_SESSION_CORRUPT);
    capri_session_free(&nul_owner_session); capri_session_free(&committed);
    sqlite3_close(raw);
    struct stat database_mode;assert(stat(path,&database_mode)==0&&(database_mode.st_mode&0777u)==0600u);
    assert(chmod(path,0644)==0);
    assert(capri_session_get_for_principal(store,session_id,"principal-alice",&bob)==CAPRI_SESSION_IO);
    assert(chmod(path,0600)==0);
    capri_session_store_close(store);

    /* A concurrent schema opener must wait for an existing writer lock. */
    int opener_start_pipe[2],opener_result_pipe[2];
    assert(pipe(opener_start_pipe)==0&&pipe(opener_result_pipe)==0);
    pid_t opener=fork(); assert(opener>=0);
    if(opener==0){
        close(opener_start_pipe[1]); close(opener_result_pipe[0]);
        unsigned char opener_go=0;
        if(read(opener_start_pipe[0],&opener_go,sizeof opener_go)!=(ssize_t)sizeof opener_go)_exit(3);
        close(opener_start_pipe[0]);
        CapriSessionError child_error=CAPRI_SESSION_INVALID;
        CapriSessionStore *child_store=capri_session_store_open(path,200,16000,64000,131072,&child_error);
        int opener_result=child_store?CAPRI_SESSION_OK:(int)child_error;
        if(child_store)capri_session_store_close(child_store);
        ssize_t written=write(opener_result_pipe[1],&opener_result,sizeof opener_result);
        close(opener_result_pipe[1]);
        _exit(written==(ssize_t)sizeof opener_result&&opener_result==CAPRI_SESSION_OK?0:1);
    }
    close(opener_start_pipe[0]); close(opener_result_pipe[1]);
    sqlite3 *lock_db=NULL;
    assert(sqlite3_open(path,&lock_db)==SQLITE_OK);
    assert(sqlite3_exec(lock_db,"PRAGMA journal_mode=DELETE; BEGIN EXCLUSIVE;",NULL,NULL,NULL)==SQLITE_OK);
    unsigned char opener_go=1;
    assert(write(opener_start_pipe[1],&opener_go,sizeof opener_go)==(ssize_t)sizeof opener_go);
    close(opener_start_pipe[1]);
    struct timespec lock_delay={0,200000000};
    assert(nanosleep(&lock_delay,NULL)==0);
    assert(sqlite3_exec(lock_db,"COMMIT",NULL,NULL,NULL)==SQLITE_OK);
    assert(sqlite3_close(lock_db)==SQLITE_OK);
    int opener_result=-1;
    assert(read(opener_result_pipe[0],&opener_result,sizeof opener_result)==(ssize_t)sizeof opener_result);
    close(opener_result_pipe[0]);
    int child_status=0; assert(waitpid(opener,&child_status,0)==opener);
    assert(WIFEXITED(child_status)&&WEXITSTATUS(child_status)==0&&opener_result==CAPRI_SESSION_OK);

    char hardlinkpath[512]; snprintf(hardlinkpath,sizeof hardlinkpath,"%s/hardlink.sqlite3",dir);
    assert(link(path,hardlinkpath)==0);
    store=capri_session_store_open(hardlinkpath,200,16000,64000,131072,&error); assert(store==NULL);
    unlink(hardlinkpath);
    char linkpath[512]; snprintf(linkpath,sizeof linkpath,"%s/symlink.sqlite3",dir);
    assert(symlink(path,linkpath)==0);
    store=capri_session_store_open(linkpath,200,16000,64000,131072,&error); assert(store==NULL);
    unlink(linkpath);
    unlink(backup_path); unlink(restored_path); unlink(corrupt_backup_path); unlink(corrupt_restore_path); unlink(path); char wal[520],shm[520];snprintf(wal,sizeof wal,"%s-wal",path);snprintf(shm,sizeof shm,"%s-shm",path);unlink(wal);unlink(shm);rmdir(dir);
    puts("native SQLite session tests: ok"); return 0;
}
