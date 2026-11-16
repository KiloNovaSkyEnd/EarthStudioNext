"""Frame-exact, consecutive scene cuts. Each source scene keeps independent weather/camera time."""

def layout(clips,scenes):
    if not clips or len(clips)>10000:raise ValueError('需要1..10000个分镜片段')
    cursor=1;result=[]
    for clip in clips:
        name=clip['scene']
        if name not in scenes:raise ValueError('未知分镜：'+name)
        bounds=scenes[name];start=clip.get('in',bounds[0]);end=clip.get('out',bounds[1])
        if type(start) is not int or type(end) is not int or not bounds[0]<=start<=end<=bounds[1]:raise ValueError('分镜入出点不在场景范围')
        length=end-start+1
        result.append(dict(scene=name,source_in=start,source_out=end,start=cursor,end=cursor+length-1))
        cursor+=length
    return result
