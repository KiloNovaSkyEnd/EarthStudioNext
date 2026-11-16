#version 330
uniform sampler2D geocolor;
uniform vec3 camera_position,camera_right,camera_up,camera_forward,sun_direction;
uniform vec4 source_extent,source_projection;
uniform vec2 resolution;
uniform float tan_half_fov;
uniform bool atmosphere_enabled,airglow_enabled;
out vec4 frag_color;
const float R=6371.;
float c2(float a,float b,float x){float t=clamp((x-a)/(b-a),0.,1.);return t*t*t*(t*(6.*t-15.)+10.);}
vec3 linear_rgb(vec3 c){return mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));}
vec3 srgb(vec3 c){c=max(c,vec3(0));return mix(12.92*c,1.055*pow(c,vec3(1./2.4))-.055,step(vec3(.0031308),c));}
vec2 source_uv(vec3 p){
    vec3 n=normalize(p);float lat=asin(clamp(n.z,-1.,1.)),lo=atan(n.y,n.x)-source_projection.w;
    float a=source_projection.x,b=source_projection.y,h=source_projection.z,e2=1.-b*b/(a*a);
    float q=a/sqrt(1.-e2*sin(lat)*sin(lat));
    vec3 v=vec3(q*cos(lat)*cos(lo),q*cos(lat)*sin(lo),q*(1.-e2)*sin(lat));
    float dx=a+h-v.x;
    if(dx*v.x-v.y*v.y-v.z*v.z/(1.-e2)<0.)return vec2(-1.);
    vec2 xy=h*vec2(atan(v.y,dx),atan(v.z,length(vec2(dx,v.y))));
    return vec2((xy.x-source_extent.x)/(source_extent.z-source_extent.x),
                (source_extent.w-xy.y)/(source_extent.w-source_extent.y));
}
vec3 sample_ray(vec3 ray,vec3 dx,vec3 dy){
    float b=dot(camera_position,ray),disc=b*b-dot(camera_position,camera_position)+R*R;
    float t=-b-sqrt(max(disc,0.));bool hit=disc>=0.&&t>0.;
    vec3 base=vec3(0.);
    if(hit){
        vec3 p=camera_position+ray*t,n=normalize(p);
        vec2 uv=source_uv(p);
        float f=-max(abs(dot(n,ray)),.03);
        vec2 ux=source_uv(p+t*(dx-ray*dot(n,dx)/f))-uv;
        vec2 uy=source_uv(p+t*(dy-ray*dot(n,dy)/f))-uv;
        if(all(greaterThanEqual(uv,vec2(0)))&&all(lessThanEqual(uv,vec2(1))))
            base=textureGrad(geocolor,uv,ux,uy).rgb;
        else base=vec3(.018,0.,.018); // explicit unobserved area
    }
    float h=length(cross(camera_position,ray))-R;
    // Broad low-saturation glow outside, only a 2km tail over real clouds.
    // Gaussian has zero slope at the attached peak; no sharp emissive line.
    float width=h<0.?2.:18.;
    float profile=exp(-.5*pow(h/width,2.));
    vec3 point=hit?camera_position+ray*t:camera_position+ray*max(-b,0.);
    float day=c2(-.104528,.104528,dot(normalize(point),sun_direction));
    float blue=atmosphere_enabled?.16*profile*day:0.;
    float warm=airglow_enabled?.12*profile*(1.-day):0.;
    if(b<0.)base=base*(1.-blue-warm)+linear_rgb(vec3(.34,.46,.59))*blue+linear_rgb(vec3(.46,.40,.32))*warm;
    return base;
}
vec3 view_ray(vec2 pixel){
    vec2 xy=(2.*pixel-resolution)/resolution.y;
    return normalize(camera_forward+tan_half_fov*(xy.x*camera_right+xy.y*camera_up));
}
void main(){
    vec3 ray=view_ray(gl_FragCoord.xy);
    vec3 dx=dFdx(ray),dy=dFdy(ray),sum=vec3(0.);
    float h=length(cross(camera_position,ray))-R;
    if(abs(h)<60.){
        for(int y=0;y<4;y++)for(int x=0;x<4;x++)
            sum+=sample_ray(view_ray(gl_FragCoord.xy+(vec2(x,y)+.5)/4.-.5),dx,dy);
        sum/=16.;
    }else sum=sample_ray(ray,dx,dy);
    frag_color=vec4(srgb(sum),1.);
}
