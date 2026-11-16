#version 330
// Native AHI measurements + explicitly approximate radial cloud volume.
// No generated cloud noise, specular sun disk, or inferred observations.
uniform sampler2D ground_day, ground_night, cloud_rgba, cloud_top;
uniform sampler2D ocean_mask;
uniform sampler2D ground_night_detail;
uniform bool night_detail_enabled;
uniform vec4 night_detail_uv; // global UV origin.xy and span.zw, north-first area pixels
uniform vec2 night_detail_feather; // one degree interior transition, no cloud-mask changes
uniform vec3 camera_position,camera_right,camera_up,camera_forward,sun_direction;
uniform vec2 resolution;
uniform vec4 source_extent; // xmin,ymin,xmax,ymax in km, actual AHI crop
uniform vec4 source_projection; // equatorial radius,polar radius,satellite altitude,lon0(rad)
uniform float tan_half_fov,height_scale,layer_thickness;
uniform bool volume_enabled,atmosphere_enabled,airglow_enabled,debug_projection;
uniform bool deep_ocean_material,ocean_reflections_enabled,city_lights_enabled,clouds_enabled;
uniform float exposure;
uniform float city_light_gain;
uniform int volume_samples;
out vec4 frag_color;
const float R=6371.,TOP=6471.,PI=3.141592653589793;
const vec3 BR=vec3(.005802,.013558,.033100),BM=vec3(.0020),BE=vec3(.0024),BO=vec3(.000650,.001881,.000085);
float c2(float a,float b,float x){float t=clamp((x-a)/(b-a),0.,1.);return t*t*t*(t*(6.*t-15.)+10.);}
vec3 linear_rgb(vec3 c){return mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));}
vec3 srgb(vec3 c){c=max(c,vec3(0));return mix(12.92*c,1.055*pow(c,vec3(1./2.4))-.055,step(vec3(.0031308),c));}
vec2 roots(vec3 p,vec3 d,float r){float b=dot(p,d),q=b*b-dot(p,p)+r*r;if(q<0.)return vec2(1e20,-1e20);float s=sqrt(q);return vec2(-b-s,-b+s);}
vec2 global_uv(vec3 p){vec3 n=normalize(p);return vec2(atan(n.y,n.x)/(2.*PI)+.5,.5-asin(clamp(n.z,-1.,1.))/PI);}

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
bool inside(vec2 uv){return uv.x>=0.&&uv.x<=1.&&uv.y>=0.&&uv.y<=1.;}
vec2 cloud_height(vec2 uv){
    if(!inside(uv))return vec2(.9,0.);
    vec2 h=textureLod(cloud_top,uv,0.).rg;
    // Continuous DISPLAY geometry confidence; no categorical jump to a shell.
    // The separate measured-support channel remains unchanged on the CPU.
    float confidence=c2(0.,.7,h.y);
    return vec2(mix(.9,.3+height_scale*h.x/max(h.y,.0001),confidence),confidence);
}
vec4 material(vec3 p,vec3 ray,vec3 dx,vec3 dy,float distance){
    vec2 uv=source_uv(p);if(!inside(uv))return vec4(0.);
    vec3 n=normalize(p);float f=dot(n,ray);f=f<0.?-max(abs(f),.03):max(abs(f),.03);
    vec2 ux=source_uv(p+distance*(dx-ray*dot(n,dx)/f))-uv;
    vec2 uy=source_uv(p+distance*(dy-ray*dot(n,dy)/f))-uv;
    vec4 c=textureGrad(cloud_rgba,uv,ux,uy);
    return vec4(c.a>.0001?linear_rgb(clamp(c.rgb/c.a,0.,1.)):vec3(0),c.a);
}
vec3 local_normal(vec3 p){
    vec2 uv=source_uv(p),e=1./vec2(textureSize(cloud_top,0));
    vec3 n=normalize(p);float longitude=atan(n.y,n.x);vec3 east=vec3(-sin(longitude),cos(longitude),0.),north=cross(n,east);
    // Radial height finite differences in world east/north, not source x/y.
    float step_km=4.;
    vec2 h0=cloud_height(uv),he=cloud_height(source_uv(p+east*step_km)),hw=cloud_height(source_uv(p-east*step_km));
    vec2 hn=cloud_height(source_uv(p+north*step_km)),hs=cloud_height(source_uv(p-north*step_km));
    float sx=(he.y*hw.y*h0.y>.5)?(he.x-hw.x)/(2.*step_km):0.;
    float sy=(hn.y*hs.y*h0.y>.5)?(hn.x-hs.x)/(2.*step_km):0.;
    return normalize(n-east*clamp(sx,-.2,.2)-north*clamp(sy,-.2,.2));
}
float column_sun_transmission(vec3 p){
    // Coarse shadow integration through the same displayed columns. Source
    // cloud colour is untouched; density/thickness are model assumptions.
    float tau=0.;
    for(int j=0;j<4;j++){
        float start=.25+float(j*j)*.65,end=.25+float((j+1)*(j+1))*.65;
        vec3 q=p+sun_direction*(start+end)*.5;vec2 uv=source_uv(q);
        if(!inside(uv))continue;
        vec2 ht=cloud_height(uv);float thick=min(layer_thickness,max(.25,.35*ht.x));
        float u=(ht.x-(length(q)-R))/thick;
        if(u<=0.||u>=1.)continue;
        float a=textureLod(cloud_rgba,uv,1.).a;
        tau+=-log(max(1.-a,.01))*6.*u*(1.-u)/thick*(end-start);
    }
    return exp(-min(tau,6.));
}
vec3 sunlight(vec3 p);
float cloud_shadow(vec3 p){
    if(!clouds_enabled)return 1.; // Diagnostic cloud OFF must also remove its surface shadow.
    float mu=dot(normalize(p),sun_direction);if(mu<=.03)return 1.;
    vec2 crossing=roots(p,sun_direction,R+3.);
    vec3 q=p+sun_direction*max(crossing.y,0.);vec2 uv=source_uv(q);
    vec2 ht=cloud_height(uv);crossing=roots(p,sun_direction,R+ht.x);
    uv=source_uv(p+sun_direction*max(crossing.y,0.));
    if(!inside(uv))return 1.;
    // Soft solar attenuation from display optical depth, NOT retrieved shadow.
    float alpha=textureLod(cloud_rgba,uv,2.).a;
    return exp(log(max(1.-alpha,.01))*.65/max(mu,.15));
}
vec3 surface(vec3 p,vec3 ray,vec3 dx,vec3 dy,float distance){
    vec3 n=normalize(p);vec2 uv=global_uv(p);
    float f=dot(n,ray);f=f<0.?-max(abs(f),.02):max(abs(f),.02);
    vec2 ux=global_uv(p+distance*(dx-ray*dot(n,dx)/f))-uv,uy=global_uv(p+distance*(dy-ray*dot(n,dy)/f))-uv;
    ux.x-=floor(ux.x+.5);uy.x-=floor(uy.x+.5);
    vec3 day=linear_rgb(textureGrad(ground_day,uv,ux,uy).rgb);
    vec3 night=linear_rgb(textureGrad(ground_night,uv,ux,uy).rgb);
    if(night_detail_enabled){
        vec2 q=(uv-night_detail_uv.xy)/night_detail_uv.zw;
        if(all(greaterThanEqual(q,vec2(0.)))&&all(lessThanEqual(q,vec2(1.)))){
            vec2 edge=min(q,1.-q)/night_detail_feather;
            float weight=smoothstep(0.,1.,min(edge.x,edge.y));
            vec3 detail=linear_rgb(textureGrad(ground_night_detail,q,ux/night_detail_uv.zw,uy/night_detail_uv.zw).rgb);
            night=mix(night,detail,weight);
        }
    }
    if(!city_lights_enabled)night=vec3(0.);
    float mu=dot(n,sun_direction),light=c2(-.06,.45,mu);
    vec3 result=day*(.002+.998*light)+night*(1.-c2(-.1045,.04,mu))*city_light_gain;
    float water=textureGrad(ocean_mask,uv,ux,uy).r;
    if(water>0.){
        vec3 v=-ray;float nv=max(dot(n,v),.001),nl=max(mu,0.);
        float fresnel=.0204+.9796*pow(1.-nv,5.);
        // Statistical rough water + reflected diffuse sky. No wave pixels,
        // sun disk or saturated specular lobe; roughness is a model assumption.
        vec3 h=normalize(v+sun_direction);float nh=max(dot(n,h),0.);
        float a2=pow(.55,4.);
        float distribution=a2/(PI*pow(max(nh*nh*(a2-1.)+1.,.0001),2.));
        float spec=distribution*.0204*nl/(4.*max(nv,.1));
        spec=.012*spec/(.012+spec);
        float sky_day=c2(-.12,.35,mu);
        vec3 sky=vec3(.045,.105,.20)*sky_day*(.45+.55*sqrt(max(1.-nv,0.)));
        vec3 incident=sunlight(p+n*.02);float shadow=cloud_shadow(p);
        // Opt-in subsurface diffuse model, not a screen tint or measured sea state.
        // Preserve bright coastal/shallow reference variation; only dark water
        // blends toward a bounded deep-water linear-RGB reflectance.
        vec3 water_diffuse=day;
        if(deep_ocean_material){
            float deep=1.-smoothstep(.012,.08,dot(day,vec3(.2126,.7152,.0722)));
            water_diffuse=mix(day,vec3(.002,.009,.025),.65*deep);
        }
        if(!ocean_reflections_enabled){sky=vec3(0.);spec=0.;}
        vec3 sea=water_diffuse*(.001+.018*sky_day+.60*nl*shadow)*(1.-fresnel)
                 +sky*fresnel+incident*spec*shadow;
        result=mix(result,sea,water);
    }
    return result;
}
vec3 density(vec3 p){float h=max(length(p)-R,0.);return vec3(exp(-h/8.),exp(-h/1.2),max(0.,1.-abs(h-25.)/15.));}
vec3 sigma(vec3 r){return BR*r.x+BE*r.y+BO*r.z;}
float visible_sun(vec3 p){float r=length(p),horizon=-sqrt(max(0.,1.-R*R/(r*r)));return c2(-.004675,.004675,dot(p/r,sun_direction)-horizon);}
vec3 sunlight(vec3 p){
    float visibility=visible_sun(p);if(visibility==0.)return vec3(0.);
    float last=max(roots(p,sun_direction,TOP).y,0.);vec3 tau=vec3(0);
    for(int j=0;j<12;j++){float a=float(j)/12.,b=float(j+1)/12.;float t0=last*a*a,t1=last*b*b;tau+=sigma(density(p+sun_direction*(t0+t1)*.5))*(t1-t0);}
    return vec3(1.47,1.85,1.91)*exp(-tau)*visibility;
}
void main(){
    vec2 screen=(2.*gl_FragCoord.xy-resolution)/resolution.y;
    vec3 ray=normalize(camera_forward+tan_half_fov*(camera_right*screen.x+camera_up*screen.y));
    vec3 dx=dFdx(ray),dy=dFdy(ray);
    vec2 ground=roots(camera_position,ray,R),atmo=roots(camera_position,ray,TOP);
    bool hit=ground.x>0.&&ground.x<1e19;
    float finish=hit?ground.x:max(atmo.y,0.);
    if(debug_projection){vec2 uv=hit?source_uv(camera_position+ray*ground.x):vec2(-1.);frag_color=vec4(uv,0,1);return;}
    vec3 base=hit?surface(camera_position+ray*ground.x,ray,dx,dy,ground.x):vec3(0);
    vec2 top=roots(camera_position,ray,R+8.4);
    float first=max(top.x,0.),last=hit?ground.x:top.y;
    vec3 cloud_light=vec3(0);float transmission=1.,cloud_front=finish;
    if(clouds_enabled&&top.y>first&&last>first){
        float ds=(last-first)/float(volume_samples);
        for(int i=0;i<192;i++){
            if(i>=volume_samples)break;
            float distance=first+(float(i)+.5)*ds;vec3 p=camera_position+ray*distance;
            vec2 uv=source_uv(p);if(!inside(uv))continue;
            vec2 ht=cloud_height(uv);float h=length(p)-R;
            float thickness=min(layer_thickness,max(.25,.35*ht.x));
            if(!volume_enabled)thickness=.25;
            // Analytic segment integral of6u(1-u). Midpoint-only sampling
            // skipped thin low clouds, producing holes even with valid RGBA.
            float radial=abs(dot(normalize(p),ray));
            float u0=clamp((ht.x-(length(camera_position+ray*(distance-ds*.5))-R))/thickness,0.,1.);
            float u1=clamp((ht.x-(length(camera_position+ray*(distance+ds*.5))-R))/thickness,0.,1.);
            float integral=abs(u1*u1*(3.-2.*u1)-u0*u0*(3.-2.*u0))/max(radial,.01);
            if(integral<=0.)continue;
            vec4 c=material(p,ray,dx,dy,distance);if(c.a<=.001)continue;
            // Extinction derived from artistic alpha, NOT retrieved optical depth.
            float alpha=1.-exp(log(max(1.-c.a,.005))*integral);
            vec3 n=normalize(p),local=local_normal(p);
            float day=c2(-.1045,.1045,dot(n,sun_direction));
            float shade=clamp(dot(local-n,sun_direction)*1.5,-.18,.18)*day;
            shade+=clamp(dot(local-n,normalize(vec3(.4,-.6,.7)))*3.,-.18,.18)*(1.-day);
            float shadow=day>.01?column_sun_transmission(p):1.;
            float direct=.30+.70*sqrt(max(dot(n,sun_direction),0.))*(.55+.45*shadow);
            vec3 illumination=mix(vec3(.82,.89,1.),vec3(direct),day);
            cloud_light+=transmission*c.rgb*illumination*(1.+shade)*alpha;
            transmission*=1.-alpha;
            if(transmission<.95)cloud_front=min(cloud_front,distance);
            if(transmission<.002)break;
        }
    }
    base=cloud_light+transmission*base;
    // Aerial perspective to front cloud for opaque regions; approximate for thin layers.
    finish=mix(finish,cloud_front,1.-transmission);
    float start=max(atmo.x,0.);finish=min(finish,atmo.y);
    if((atmosphere_enabled||airglow_enabled)&&finish>start){
        float closest=clamp(-dot(camera_position,ray),start,finish);
        vec3 tau=vec3(0),light=vec3(0);float mu=dot(ray,sun_direction);
        float pr=3.*(1.+mu*mu)/(16.*PI),g=.8,pm=(1.-g*g)/(4.*PI*pow(max(1.+g*g-2.*g*mu,.0001),1.5));
        for(int i=0;i<48;i++){
            float a=float(i)/48.,b=float(i+1)/48.;float t0=start+(finish-start)*a,t1=start+(finish-start)*b;
            // Split quadrature at closest approach, deterministic and C0 consistent.
            if(closest>start&&closest<finish){
                float q0=2.*a,q1=2.*b;
                t0=q0<1.?mix(start,closest,1.-pow(1.-q0,2.)):mix(closest,finish,pow(q0-1.,2.));
                t1=q1<1.?mix(start,closest,1.-pow(1.-q1,2.)):mix(closest,finish,pow(q1-1.,2.));
            }
            vec3 p=camera_position+ray*(t0+t1)*.5,rho=density(p);float ds=t1-t0;
            vec3 ext=atmosphere_enabled?sigma(rho):vec3(0),source=vec3(0);
            if(atmosphere_enabled)source=(BR*rho.x*pr+BM*rho.y*pm)*sunlight(p)*1.2;
            if(airglow_enabled){float h=length(p)-R,night=1.-c2(-.12,.04,dot(normalize(p),sun_direction));
                source+=vec3(.8,.38,.10)*exp(-.5*pow((h-90.)/7.,2.))*night*.000015;}
            vec3 st=ext*ds,integral=mix(vec3(ds),(1.-exp(-st))/max(ext,vec3(1e-9)),step(vec3(1e-8),ext));
            light+=exp(-tau)*source*integral;tau+=st;
        }
        base=base*exp(-tau)+light;
    }
    if(exposure!=1.)base*=exposure;
    frag_color=vec4(clamp(srgb(base),0.,1.),1.);
}
