import sys,json,hashlib
from pathlib import Path
import av,numpy as np
path=Path(sys.argv[1]);w,h,fps=map(int,sys.argv[2:5])
if path.exists():raise FileExistsError(path)
c=av.open(str(path),'w');s=c.add_stream('libx264',rate=fps);s.width=w;s.height=h;s.pix_fmt='yuv420p';s.options={'crf':'18'}
n=0;size=w*h*3
while True:
    chunks=[];remaining=size
    while remaining:
        b=sys.stdin.buffer.read(remaining)
        if not b:
            if remaining!=size:raise ValueError('Partial RGB frame')
            break
        chunks.append(b);remaining-=len(b)
    if remaining==size:break
    rgb=np.frombuffer(b''.join(chunks),np.uint8).reshape(h,w,3)
    for packet in s.encode(av.VideoFrame.from_ndarray(rgb,format='rgb24')):c.mux(packet)
    n+=1
for packet in s.encode():c.mux(packet)
c.close()
with av.open(str(path)) as video:decoded=sum(1 for _ in video.decode(video=0))
if decoded!=n:raise RuntimeError('Decoded frame count mismatch')
(path.with_suffix('.json')).write_text(json.dumps({'frames':n,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'fps':fps},indent=2))
