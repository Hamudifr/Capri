use std::time::Instant;
const W:usize=256; const H:usize=256; const G:usize=80; const N:usize=W*H;
fn main() {
    let mut current=vec![0_u8;N]; let mut next=vec![0_u8;N];
    for r in 0..H { for c in 0..W { let i=r*W+c; current[i]=if (i*17+r*31+7)%11<5 {1} else {0}; } }
    let start=Instant::now();
    for _ in 0..G {
        for r in 0..H {
            let up=(if r==0 {H-1} else {r-1})*W; let mid=r*W;
            let down=(if r+1==H {0} else {r+1})*W;
            for c in 0..W {
                let left=if c==0 {W-1} else {c-1}; let right=if c+1==W {0} else {c+1}; let i=mid+c;
                let n=current[up+left] as u32+current[up+c] as u32+current[up+right] as u32+
                    current[mid+left] as u32+current[mid+right] as u32+
                    current[down+left] as u32+current[down+c] as u32+current[down+right] as u32;
                let alive=current[i]; next[i]=if n==3||(alive!=0&&n==2) {1} else {0};
            }
        }
        std::mem::swap(&mut current,&mut next);
    }
    let elapsed=start.elapsed().as_nanos();
    let mut hash=14_695_981_039_346_656_037_u64;
    for cell in current { hash^=cell as u64; hash=hash.wrapping_mul(1_099_511_628_211); }
    println!("RESULT {elapsed} {hash:016x}");
}
