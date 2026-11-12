# -*- coding: utf-8 -*-
import io,sys,os
os.environ["HF_ENDPOINT"]="https://hf-mirror.com"
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding="utf-8",errors="replace")
from PIL import Image
import numpy as np
from transformers import pipeline
src,dst=sys.argv[1],sys.argv[2]
im=Image.open(src).convert("RGB")
pipe=pipeline("depth-estimation",model="depth-anything/Depth-Anything-V2-Small-hf",device=-1)
out=pipe(im)["depth"]
a=np.array(out).astype(np.float32)
a=(a-a.min())/(a.max()-a.min()+1e-6)
# Depth-Anything: 近=数值大 → 转成"近处亮"
a=(a*255).astype(np.uint8)
Image.fromarray(a).save(dst)
print("深度图写出",dst,im.size,"→近处亮")