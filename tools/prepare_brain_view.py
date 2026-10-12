"""Create factual 3D brain points from the official MaleCNS neuropil labels."""
from pathlib import Path
import json
import numpy as np
import pyarrow as pa
root=Path(__file__).resolve().parents[1]
reader=pa.ipc.open_file(pa.memory_map(str(root/"data/raw/syn-partners-male-cns-v1.0-minconf-0.5.feather"),"r"))
rois=reader.get_batch(0).column(reader.schema.get_field_index("primary_post")).dictionary.to_pylist()
brain_rois=rois[1:rois.index("gL(R)")+1]+["CentralBrain-unspecified","Optic-unspecified(L)","Optic-unspecified(R)"]
points=[];row_base=0
for bi in range(reader.num_record_batches):
    batch=reader.get_batch(bi)
    if bi%5==0:
        roi=batch.column(batch.schema.get_field_index("primary_post"))
        codes=roi.indices.to_numpy()
        allowed=np.array([name in brain_rois for name in roi.dictionary.to_pylist()])
        rows=np.arange(0,batch.num_rows,280);rows=rows[allowed[codes[rows]]]
        cols=[batch.column(batch.schema.get_field_index(n)).to_numpy() for n in ["x_post","y_post","z_post","body_post"]]
        for i in rows:points.append([int(cols[0][i]),int(cols[1][i]),int(cols[2][i]),str(int(cols[3][i])),int(row_base+i)])
    row_base+=batch.num_rows
    if bi%500==0:print(f"batch {bi}/{reader.num_record_batches}; brain samples {len(points)}",flush=True)
if len(points)>24000:points=[points[i] for i in np.linspace(0,len(points)-1,24000,dtype=int)]
out=root/"web/data/brain.json";out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({"source":"MaleCNS v1.0 / HHMI Janelia","license":"CC-BY-4.0","coordinates":"8 nm voxel units: x_post,y_post,z_post","sampling":"Every fifth batch, every 280th row, brain ROI filter, deterministic downsample","brain_rois":brain_rois,"points":points},separators=(",",":")),encoding="utf-8")
print(f"Saved {len(points)} points",flush=True)

