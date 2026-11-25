#include "capri_core.h"
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

static void err(char *p, size_t n, const char *s) {
    if (p != NULL && n != 0u) (void)snprintf(p, n, "%s", s);
}
static bool utf8(const unsigned char *s, size_t n) {
    size_t i = 0u;
    while (i < n) {
        unsigned char a = s[i];
        if (a < 0x80u) { ++i; continue; }
        if (a >= 0xC2u && a <= 0xDFu) {
            if (i + 1u >= n || s[i+1u] < 0x80u || s[i+1u] > 0xBFu) return false;
            i += 2u; continue;
        }
        if (a >= 0xE0u && a <= 0xEFu) {
            if (i + 2u >= n) return false;
            unsigned char b=s[i+1u], c=s[i+2u];
            if (c < 0x80u || c > 0xBFu) return false;
            if (a==0xE0u) { if (b<0xA0u || b>0xBFu) return false; }
            else if (a==0xEDu) { if (b<0x80u || b>0x9Fu) return false; }
            else if (b<0x80u || b>0xBFu) return false;
            i += 3u; continue;
        }
        if (a >= 0xF0u && a <= 0xF4u) {
            if (i + 3u >= n) return false;
            unsigned char b=s[i+1u], c=s[i+2u], d=s[i+3u];
            if (c<0x80u || c>0xBFu || d<0x80u || d>0xBFu) return false;
            if (a==0xF0u) { if (b<0x90u || b>0xBFu) return false; }
            else if (a==0xF4u) { if (b<0x80u || b>0x8Fu) return false; }
            else if (b<0x80u || b>0xBFu) return false;
            i += 4u; continue;
        }
        return false;
    }
    return true;
}
static bool field(const char *s, size_t cap, bool required) {
    const char *z = memchr(s, '\0', cap);
    if (z == NULL) return false;
    size_t n = (size_t)(z-s);
    if (required && n == 0u) return false;
    return utf8((const unsigned char *)s, n);
}
static bool nonblank(const char *s) {
    for (; *s != '\0'; ++s)
        if (*s!=' ' && *s!='\t' && *s!='\n' && *s!='\r' && *s!='\f' && *s!='\v') return true;
    return false;
}
static bool digs(const char *s, size_t n) {
    for (size_t i=0u;i<n;++i) if (s[i]<'0' || s[i]>'9') return false;
    return true;
}
static int num(const char *s,size_t n) {
    int v=0; for(size_t i=0u;i<n;++i) v=v*10+(s[i]-'0'); return v;
}
static bool leap(int y) { return y%4==0 && (y%100!=0 || y%400==0); }
static bool timestamp(const char *s) {
    size_t n=strlen(s);
    if(n<20u || n>CAPRI_TIMESTAMP_MAX || !digs(s,4u) || s[4]!='-' ||
       !digs(s+5u,2u) || s[7]!='-' || !digs(s+8u,2u) ||
       (s[10]!='T' && s[10]!='t') || !digs(s+11u,2u) ||
       s[13]!=':' || !digs(s+14u,2u) || s[16]!=':' || !digs(s+17u,2u)) return false;
    int y=num(s,4u),m=num(s+5u,2u),d=num(s+8u,2u);
    int h=num(s+11u,2u),mi=num(s+14u,2u),se=num(s+17u,2u);
    static const int md[]={31,28,31,30,31,30,31,31,30,31,30,31};
    if(y<1 || m<1 || m>12 || h>23 || mi>59 || se>59) return false;
    int last=md[m-1]+((m==2 && leap(y))?1:0);
    if(d<1 || d>last) return false;
    size_t p=19u;
    if(p<n && s[p]=='.') {
        size_t begin=++p; while(p<n && s[p]>='0' && s[p]<='9') ++p;
        if(p==begin) return false;
    }
    if(p<n && (s[p]=='Z' || s[p]=='z')) return p+1u==n;
    if(p+6u!=n || (s[p]!='+' && s[p]!='-') || !digs(s+p+1u,2u) ||
       s[p+3u]!=':' || !digs(s+p+4u,2u)) return false;
    return num(s+p+1u,2u)<=23 && num(s+p+4u,2u)<=59;
}
static bool dimension(const char *s) {
    static const char *const a[]={"Agency","Reasoning","Memory","Adaptability","Reliability","Cross-skill"};
    for(size_t i=0u;i<sizeof(a)/sizeof(a[0]);++i) if(strcmp(s,a[i])==0) return true;
    return false;
}
CapriRecordError capri_record_validate(const CapriEvaluationRecord *r,char *e,size_t n) {
    if(r==NULL){err(e,n,"record must not be null");return CAPRI_RECORD_NULL;}
    const char *req[]={r->run_id,r->scenario_id,r->dimension,r->run_at};
    const size_t rc[]={sizeof r->run_id,sizeof r->scenario_id,sizeof r->dimension,sizeof r->run_at};
    for(size_t i=0u;i<4u;++i) {
        if(memchr(req[i],'\0',rc[i])==NULL || !nonblank(req[i])) {
            err(e,n,"required field is empty or unterminated");return CAPRI_RECORD_REQUIRED_FIELD;
        }
        if(!field(req[i],rc[i],true)){err(e,n,"field contains invalid UTF-8");return CAPRI_RECORD_INVALID_UTF8;}
    }
    const char *opt[]={r->evidence_ref,r->parent_run_id,r->rubric_version};
    const size_t oc[]={sizeof r->evidence_ref,sizeof r->parent_run_id,sizeof r->rubric_version};
    for(size_t i=0u;i<3u;++i) {
        if(memchr(opt[i],'\0',oc[i])==NULL){err(e,n,"optional field is unterminated");return CAPRI_RECORD_INVALID_UTF8;}
        if(opt[i][0]!='\0' && (!nonblank(opt[i]) || !field(opt[i],oc[i],false))) {
            err(e,n,"optional field is blank or invalid UTF-8");return CAPRI_RECORD_INVALID_UTF8;
        }
    }
    if(!dimension(r->dimension)){err(e,n,"dimension is not in the controlled vocabulary");return CAPRI_RECORD_INVALID_DIMENSION;}
    if(r->status<CAPRI_STATUS_NOT_RUN || r->status>CAPRI_STATUS_RETEST_NEEDED ||
       r->evaluator_type<CAPRI_EVALUATOR_SELF || r->evaluator_type>CAPRI_EVALUATOR_INDEPENDENT ||
       r->evidence_stage<CAPRI_EVIDENCE_NOT_RUN || r->evidence_stage>CAPRI_EVIDENCE_INDEPENDENTLY_REVIEWED) {
        err(e,n,"unsupported enum value");return CAPRI_RECORD_INVALID_ENUM;
    }
    if(!timestamp(r->run_at)){err(e,n,"run_at must be timezone-aware RFC 3339");return CAPRI_RECORD_INVALID_TIMESTAMP;}
    if((r->status==CAPRI_STATUS_PASS || r->status==CAPRI_STATUS_FAIL) &&
       (!nonblank(r->evidence_ref) ||
        (r->evidence_stage!=CAPRI_EVIDENCE_SELF_SCORED && r->evidence_stage!=CAPRI_EVIDENCE_INDEPENDENTLY_REVIEWED))) {
        err(e,n,"Pass/Fail requires evidence and a completed scoring stage");return CAPRI_RECORD_INVALID_EVIDENCE;
    }
    if(r->status==CAPRI_STATUS_NOT_RUN &&
       (r->evidence_stage!=CAPRI_EVIDENCE_NOT_RUN || r->evidence_ref[0]!='\0')) {
        err(e,n,"Not Run requires Not Run evidence stage and no evidence reference");return CAPRI_RECORD_INVALID_EVIDENCE;
    }
    if((r->evidence_stage==CAPRI_EVIDENCE_INDEPENDENTLY_REVIEWED && r->evaluator_type!=CAPRI_EVALUATOR_INDEPENDENT) ||
       (r->evaluator_type==CAPRI_EVALUATOR_INDEPENDENT && r->evidence_stage!=CAPRI_EVIDENCE_INDEPENDENTLY_REVIEWED) ||
       (r->evidence_stage==CAPRI_EVIDENCE_SELF_SCORED && r->evaluator_type!=CAPRI_EVALUATOR_SELF)) {
        err(e,n,"evaluator type and evidence stage are inconsistent");return CAPRI_RECORD_INVALID_EVIDENCE;
    }
    if(r->parent_run_id[0]!='\0' && strcmp(r->parent_run_id,r->run_id)==0) {
        err(e,n,"a run cannot be its own parent");return CAPRI_RECORD_INVALID_LINEAGE;
    }
    err(e,n,"");return CAPRI_RECORD_VALID;
}
const char *capri_record_error_string(CapriRecordError e) {
    static const char *const m[]={"valid","record is null","required field is empty","invalid UTF-8",
      "invalid dimension","invalid enum","invalid timestamp","invalid evidence state","invalid lineage"};
    if(e<CAPRI_RECORD_VALID || e>CAPRI_RECORD_INVALID_LINEAGE) return "unknown record error";
    return m[e];
}