#define _POSIX_C_SOURCE 200809L
#include "capri_session_store.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <sqlite3.h>
#include <pthread.h>

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
    CapriSessionError error; CapriSessionStore *store=capri_session_store_open(path,200,16000,64000,131072,&error);
    assert(store!=NULL && error==CAPRI_SESSION_OK);
    CapriSession alice={0}, bob={0}, committed={0};
    assert(capri_session_create_for_principal(store,"principal-alice",&alice)==CAPRI_SESSION_OK);
    assert(alice.version==0 && !alice.closed && strcmp(alice.messages_json,"[]")==0);
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
    capri_session_free(&a.output); capri_session_free(&b.output); capri_session_free(&race_session); capri_session_store_close(store2);
    capri_session_store_close(store);
    char linkpath[512]; snprintf(linkpath,sizeof linkpath,"%s/symlink.sqlite3",dir);
    assert(symlink(path,linkpath)==0);
    store=capri_session_store_open(linkpath,200,16000,64000,131072,&error); assert(store==NULL);
    unlink(linkpath);
    unlink(path); char wal[520],shm[520];snprintf(wal,sizeof wal,"%s-wal",path);snprintf(shm,sizeof shm,"%s-shm",path);unlink(wal);unlink(shm);rmdir(dir);
    puts("native SQLite session tests: ok"); return 0;
}
