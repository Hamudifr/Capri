#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <vector>
constexpr std::size_t W=256,H=256,G=80,N=W*H;
int main() {
    std::vector<std::uint8_t> current(N,0), next(N,0);
    for(std::size_t r=0;r<H;++r) for(std::size_t c=0;c<W;++c) {
        std::size_t i=r*W+c; current[i]=((i*17U+r*31U+7U)%11U)<5U?1U:0U;
    }
    auto start=std::chrono::steady_clock::now();
    for(std::size_t g=0;g<G;++g) {
        for(std::size_t r=0;r<H;++r) {
            std::size_t up=(r==0?H-1:r-1)*W, mid=r*W, down=(r+1==H?0:r+1)*W;
            for(std::size_t c=0;c<W;++c) {
                std::size_t left=c==0?W-1:c-1, right=c+1==W?0:c+1, i=mid+c;
                unsigned n=current[up+left]+current[up+c]+current[up+right]+current[mid+left]+current[mid+right]+current[down+left]+current[down+c]+current[down+right];
                auto alive=current[i]; next[i]=(n==3U||(alive!=0U&&n==2U))?1U:0U;
            }
        }
        current.swap(next);
    }
    auto stop=std::chrono::steady_clock::now();
    auto elapsed=std::chrono::duration_cast<std::chrono::nanoseconds>(stop-start).count();
    std::uint64_t hash=UINT64_C(14695981039346656037);
    for(auto cell:current) { hash^=cell; hash*=UINT64_C(1099511628211); }
    std::printf("RESULT %lld %016llx\n",static_cast<long long>(elapsed),(unsigned long long)hash);
}
