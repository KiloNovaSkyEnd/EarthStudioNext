#version 330
// Original single-scattering quadrature. Distances km; coefficients km^-1.
// Not Bruneton's precomputed multiple-scattering implementation.
uniform vec3 camera_position, camera_right, camera_up, camera_forward, sun_direction;
uniform vec2 resolution;
uniform float tan_half_fov, scattering_exposure, airglow_gain;
uniform int view_samples, sun_samples;
uniform bool atmosphere_enabled, airglow_enabled, dynamic_surface;
uniform sampler2D current_surface, frozen_day, frozen_night;
uniform sampler2D independent_cloud, cloud_height;
uniform bool separate_cloud_enabled;
uniform float relief_strength, night_depth_strength;
uniform sampler2D ocean_mask;
uniform bool stable_cloud_sampling, ocean_material_enabled;
out vec4 frag_color;
const float R=6371.0, TOP=6471.0, PI=3.141592653589793;
const vec3 BR=vec3(0.005802,0.013558,0.033100);
const vec3 BM=vec3(0.003996), BE=vec3(0.004440);
const vec3 BO=vec3(0.000650,0.001881,0.000085);

float c2(float a,float b,float x){float t=clamp((x-a)/(b-a),0.,1.);return t*t*t*(t*(6.*t-15.)+10.);}
vec3 linear_rgb(vec3 c){return mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));}
vec3 srgb(vec3 c){c=max(c,vec3(0));return mix(c*12.92,1.055*pow(c,vec3(1./2.4))-.055,step(vec3(.0031308),c));}
vec2 roots(vec3 p,vec3 d,float radius){
    float b=dot(p,d),disc=b*b-dot(p,p)+radius*radius;
    if(disc<0.)return vec2(1e20,-1e20);
    float s=sqrt(max(disc,0.));return vec2(-b-s,-b+s);
}
vec3 density(vec3 p){
    float h=max(length(p)-R,0.);
    // Ozone is an approximate triangular 10..40km absorption profile.
    return vec3(exp(-h/8.),exp(-h/1.2),max(0.,1.-abs(h-25.)/15.));
}
vec3 sigma(vec3 rho){return BR*rho.x+BE*rho.y+BO*rho.z;}
float sun_visibility(vec3 p){
    float r=length(p),mu=dot(p,sun_direction)/r;
    float horizon=-sqrt(max(0.,1.-R*R/(r*r)));
    // Finite angular solar disk: smooth geometric eclipse, not a hard switch.
    return c2(-.004675,.004675,mu-horizon);
}
vec3 sunlight(vec3 p){
    float vis=sun_visibility(p);if(vis<=0.)return vec3(0.);
    float distance=max(roots(p,sun_direction,TOP).y,0.);vec3 tau=vec3(0.);
    for(int j=0;j<32;j++){
        if(j>=sun_samples)break;
        float u0=float(j)/float(sun_samples),u1=float(j+1)/float(sun_samples);
        float t0=distance*u0*u0,t1=distance*u1*u1;
        tau+=sigma(density(p+sun_direction*((t0+t1)*.5)))*(t1-t0);
    }
    return vec3(1.47,1.85,1.91)*exp(-tau)*vis;
}
float sample_position(float u,float first,float closest,float last){
    if(closest>=last-.0001)return first+(last-first)*(1.-(1.-u)*(1.-u));
    if(closest<=first+.0001)return first+(last-first)*u*u;
    if(u<.5){float a=2.*u;return first+(closest-first)*(1.-(1.-a)*(1.-a));}
    float a=2.*u-1.;return closest+(last-closest)*a*a;
}
vec3 surface(vec3 point){
    vec3 n=normalize(point);
    vec2 uv=vec2(atan(n.y,n.x)/(2.*PI)+.5,.5-asin(clamp(n.z,-1.,1.))/PI);
    vec2 dx=dFdx(uv),dy=dFdy(uv);
    // Longitude wraps: a tiny date-line footprint must not select a global
    // coarse mip because atan jumps by one whole texture coordinate.
    dx.x-=floor(dx.x+.5);dy.x-=floor(dy.x+.5);
    if(ocean_material_enabled){
        float water=textureLod(ocean_mask,uv,0.).r;
        if(water>0.){
            vec3 v=normalize(camera_position-point),l=sun_direction;
            float nl=max(dot(n,l),0.),nv=max(dot(n,v),.0001);
            vec3 halfway=length(v+l)>.00001?normalize(v+l):n;
            float nh=max(dot(n,halfway),0.),vh=max(dot(v,halfway),0.);
            // Smooth statistical water microfacets, no invented wave texture.
            // Fixed roughness is a display assumption, not observed wind.
            float a2=pow(.32,4.);
            float d=a2/(PI*pow(max(nh*nh*(a2-1.)+1.,.00001),2.));
            float k=pow(.32+1.,2.)/8.;
            float g=(nv/(nv*(1.-k)+k))*(nl/(nl*(1.-k)+k));
            float f=.0204+.9796*pow(1.-vh,5.);
            float spec=d*g*f/max(4.*nv*nl,.00001)*nl;
            vec3 day=linear_rgb(textureGrad(frozen_day,uv,dx,dy).rgb)*nl;
            vec3 night=linear_rgb(textureGrad(frozen_night,uv,dx,dy).rgb)*(1.-c2(-.104528,.104528,dot(n,l)));
            // Reference-colour diffuse + bounded microfacet reflection; the
            // existing atmosphere supplies camera-path scattering separately.
            vec3 sea=day+night+min(spec,2.)*sunlight(point);
            vec3 old=linear_rgb(textureGrad(current_surface,uv,dx,dy).rgb);
            return mix(old,sea,water);
        }
    }
    if(dynamic_surface){
        float day=c2(.1,.3,dot(n,sun_direction));
        return mix(linear_rgb(textureGrad(frozen_night,uv,dx,dy).rgb),linear_rgb(textureGrad(frozen_day,uv,dx,dy).rgb),day);
    }
    return linear_rgb(textureGrad(current_surface,uv,dx,dy).rgb);
}
vec2 geo_uv(vec3 p){vec3 n=normalize(p);return vec2(atan(n.y,n.x)/(2.*PI)+.5,.5-asin(clamp(n.z,-1.,1.))/PI);}
float supported_height(vec2 uv){
    ivec2 size=textureSize(cloud_height,0);
    ivec2 cell=ivec2(floor(vec2(fract(uv.x),clamp(uv.y,0.,.999999))*vec2(size)));
    if(texelFetch(cloud_height,cell,0).g<.5)return 0.;
    vec2 sample_height=textureLod(cloud_height,uv,0.).rg;
    return sample_height.r/max(sample_height.g,.00001);
}
float display_height(vec3 p){return .3+relief_strength*supported_height(geo_uv(p));}
float cloud_intersection(vec3 ray){
    if(relief_strength==0.){vec2 sheet=roots(camera_position,ray,R+.3);return sheet.x>0.&&sheet.x<1e19?sheet.x:-1.;}
    // Restrained height field, not a volumetric reconstruction. No noise.
    vec2 shell=roots(camera_position,ray,R+.3+20.*relief_strength);
    vec2 bottom=roots(camera_position,ray,R+.3);
    float first=max(shell.x,0.),last=bottom.x>0.&&bottom.x<1e19?bottom.x:shell.y;
    if(shell.y<=first||last<=first)return -1.;
    float previous=first;
    for(int i=1;i<=64;i++){
        float t=mix(first,last,float(i)/64.);vec3 p=camera_position+ray*t;
        if(length(p)-R<=display_height(p)+.0001){
            float a=previous,b=t;
            for(int j=0;j<12;j++){float c=(a+b)*.5;vec3 q=camera_position+ray*c;if(length(q)-R>display_height(q))a=c;else b=c;}
            return (a+b)*.5;
        }
        previous=t;
    }
    return -1.;
}
vec4 cloud_sample(vec3 p,vec3 ray,vec3 ray_dx,vec3 ray_dy,float distance){
    vec2 uv=geo_uv(p),dx=dFdx(uv),dy=dFdy(uv);
    if(stable_cloud_sampling){
        // Ray differentials on the local constant-height tangent plane.
        // Height-quality steps must not inflate dFdx(uv) into a huge mipmap
        // footprint and erase/stretch fine observed cloud texture.
        vec3 radial=normalize(p);float incidence=dot(radial,ray);
        float divisor=incidence<0.?-max(abs(incidence),.02):max(abs(incidence),.02);
        vec3 px=p+distance*(ray_dx-ray*dot(radial,ray_dx)/divisor);
        vec3 py=p+distance*(ray_dy-ray*dot(radial,ray_dy)/divisor);
        dx=geo_uv(px)-uv;dy=geo_uv(py)-uv;
    }
    dx.x-=floor(dx.x+.5);dy.x-=floor(dy.x+.5);
    vec4 c=textureGrad(independent_cloud,uv,dx,dy);
    if(c.a<=.00001)return vec4(0.);
    // No global Lambert multiplier: VIS already contains observed illumination.
    // Differential height-normal cue only, capped at +/-4% in linear light.
    vec2 e=4./vec2(textureSize(cloud_height,0));
    float dhx=supported_height(uv+vec2(e.x,0))-supported_height(uv-vec2(e.x,0));
    float dhy=supported_height(uv+vec2(0,e.y))-supported_height(uv-vec2(0,e.y));
    vec3 n=normalize(p);float longitude=atan(n.y,n.x);
    vec3 east=vec3(-sin(longitude),cos(longitude),0.),north=cross(n,east);
    float sx=dhx*relief_strength/max(4.*PI*R*e.x*sqrt(max(1.-n.z*n.z,.0001)),.001);
    float sy=-dhy*relief_strength/(2.*PI*R*e.y);
    vec3 local=normalize(n-east*clamp(sx,-.25,.25)-north*clamp(sy,-.25,.25));
    float cue=clamp(dot(local-n,sun_direction)*.3,-.04,.04)*c2(0.,.15,dot(n,sun_direction))*step(.0001,supported_height(uv));
    // Optional illustrative IR depth cue, NOT sunlight/moonlight or a retrieval.
    // Fixed Earth-frame direction avoids camera-driven crawling. Geometry,
    // source RGB/opacity and daytime lighting stay unchanged.
    float night=1.-c2(-.104528463,.104528463,dot(n,sun_direction));
    vec3 display_key=normalize(vec3(.4,-.6,.7));
    float night_cue=clamp(dot(local-n,display_key)*4.,-.18,.18)*step(.0001,supported_height(uv));
    return vec4(linear_rgb(clamp(c.rgb/c.a,0.,1.))*(1.+cue+night_depth_strength*night*night_cue),c.a);
}
void main(){
    vec2 screen=(2.*gl_FragCoord.xy-resolution)/resolution.y;
    vec3 ray=normalize(camera_forward+tan_half_fov*(camera_right*screen.x+camera_up*screen.y));
    vec3 ray_dx=dFdx(ray),ray_dy=dFdy(ray);
    vec2 ground=roots(camera_position,ray,R),atmo=roots(camera_position,ray,TOP);
    bool hit=ground.x>0. && ground.x<1e19;
    float finish=hit?ground.x:max(atmo.y,0.);
    vec3 base=hit?surface(camera_position+ray*ground.x):vec3(0.);
    if(separate_cloud_enabled){
        float ct=cloud_intersection(ray);
        if(ct>0. && (!hit||ct<=ground.x)){
            vec4 cloud=cloud_sample(camera_position+ray*ct,ray,ray_dx,ray_dy,ct);
            // Existing cloud display uses sRGB over, preserving its night palette.
            base=linear_rgb(srgb(cloud.rgb)*cloud.a+srgb(base)*(1.-cloud.a));
        }
    }
    float start=max(atmo.x,0.);finish=min(finish,atmo.y);
    if((!atmosphere_enabled&&!airglow_enabled)||finish<=start){frag_color=vec4(clamp(srgb(base),0.,1.),1.);return;}
    float closest=clamp(-dot(camera_position,ray),start,finish);
    vec3 tau=vec3(0.),light=vec3(0.);
    float mu=dot(ray,sun_direction),phase_r=3.*(1.+mu*mu)/(16.*PI);
    float g=.8,phase_m=(1.-g*g)/(4.*PI*pow(max(1.+g*g-2.*g*mu,.0001),1.5));
    for(int i=0;i<192;i++){
        if(i>=view_samples)break;
        float t0=sample_position(float(i)/float(view_samples),start,closest,finish);
        float t1=sample_position(float(i+1)/float(view_samples),start,closest,finish),ds=t1-t0;
        if(ds<=0.)continue;
        vec3 p=camera_position+ray*((t0+t1)*.5),rho=density(p);
        vec3 extinction=atmosphere_enabled?sigma(rho):vec3(0.);
        vec3 source=vec3(0.);
        if(atmosphere_enabled)source=(BR*rho.x*phase_r+BM*rho.y*phase_m)*sunlight(p)*scattering_exposure;
        if(airglow_enabled){
            float h=length(p)-R;
            // Emission density integrated through a volume, not a screen ring.
            float night=1.-c2(-.12,.08,dot(normalize(p),sun_direction));
            source+=vec3(.9,.38,.09)*exp(-.5*pow((h-90.)/8.,2.))*night*.000025*airglow_gain;
        }
        vec3 step_tau=extinction*ds;
        vec3 integral=mix(vec3(ds),(1.-exp(-step_tau))/max(extinction,vec3(1e-9)),step(vec3(1e-8),extinction));
        light+=exp(-tau)*source*integral;tau+=step_tau;
    }
    // Surface display is an observed composite, not calibrated ground radiance.
    // This is camera-path aerial perspective; no atmospheric observations added.
    vec3 final_linear=base*exp(-tau)+light;
    frag_color=vec4(clamp(srgb(final_linear),0.,1.),1.);
}
