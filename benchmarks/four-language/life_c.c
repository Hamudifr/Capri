#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
enum { WIDTH = 256, HEIGHT = 256, GENERATIONS = 80 };
#define CELLS ((size_t)WIDTH * (size_t)HEIGHT)
static uint64_t now_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) { perror("clock_gettime"); exit(2); }
    return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}
int main(void) {
    uint8_t *current = (uint8_t *)calloc(CELLS, 1), *next = (uint8_t *)calloc(CELLS, 1);
    if (!current || !next) { fprintf(stderr, "allocation failed\n"); free(current); free(next); return 2; }
    for (size_t r=0; r<HEIGHT; ++r) for (size_t c=0; c<WIDTH; ++c) {
        size_t i=r*WIDTH+c; current[i]=((i*17U+r*31U+7U)%11U)<5U?1U:0U;
    }
    uint64_t start=now_ns();
    for (size_t g=0; g<GENERATIONS; ++g) {
        for (size_t r=0; r<HEIGHT; ++r) {
            size_t up=(r==0?HEIGHT-1:r-1)*WIDTH, mid=r*WIDTH, down=(r+1==HEIGHT?0:r+1)*WIDTH;
            for (size_t c=0; c<WIDTH; ++c) {
                size_t left=c==0?WIDTH-1:c-1, right=c+1==WIDTH?0:c+1, i=mid+c;
                unsigned n=current[up+left]+current[up+c]+current[up+right]+current[mid+left]+current[mid+right]+current[down+left]+current[down+c]+current[down+right];
                uint8_t alive=current[i]; next[i]=(n==3U||(alive!=0U&&n==2U))?1U:0U;
            }
        }
        uint8_t *swap=current; current=next; next=swap;
    }
    uint64_t elapsed=now_ns()-start, hash=UINT64_C(14695981039346656037);
    for (size_t i=0; i<CELLS; ++i) { hash^=current[i]; hash*=UINT64_C(1099511628211); }
    printf("RESULT %llu %016llx\n",(unsigned long long)elapsed,(unsigned long long)hash);
    free(current); free(next); return 0;
}
