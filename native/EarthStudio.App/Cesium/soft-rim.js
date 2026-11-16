/* Approved world-space soft rim, ported to WGS84 rays; independent display switches. */
(function(root){
 function weights(h,sunDot,settings){const w=h<0?2000:18000,t=Math.max(0,Math.min(1,(sunDot+.104528)/.209056)),day=t*t*t*(t*(6*t-15)+10),profile=Math.exp(-.5*(h/w)**2);return {blue:settings.blueAtmosphere?.16*profile*day:0,warm:settings.nightAirglow?.12*profile*(1-day):0};}
 function create(viewer,C){
  let settings={blueAtmosphere:false,nightAirglow:false,...EarthAirglowTransport.defaults};
  const fragmentShader=`uniform sampler2D colorTexture;
uniform bool blueOn;
uniform bool warmOn;
in vec2 v_textureCoordinates;
vec3 linearRGB(vec3 c){return mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));}
vec3 displayRGB(vec3 c){return mix(c*12.92,1.055*pow(max(c,vec3(0.)),vec3(1./2.4))-.055,step(vec3(.0031308),c));}
${EarthAirglowTransport.glsl}
void main(){
 vec4 original=texture(colorTexture,v_textureCoordinates);out_FragColor=original;
 if(!blueOn&&!warmOn&&!newOn)return;
 vec4 eye=czm_inverseProjection*vec4(v_textureCoordinates*2.-1.,1.,1.);
 // At an infinite far plane eye.w can be0. Only a direction is needed.
 vec3 ray=normalize(czm_inverseViewRotation*eye.xyz);
 vec3 invR=vec3(1./6378137.,1./6378137.,1./6356752.314245);
 // Dimensionless ray units avoid squaring1e-7 direction components.
 vec3 shape=vec3(1.,1.,6378137./6356752.314245);
 vec3 o=czm_viewerPositionWC*invR,d=ray*shape;
 float a=dot(d,d),t=-dot(o,d)/a;
 vec3 closest=o+t*d;float impact=length(closest),h=(impact-1.)*6371000.;
 float width=h<0.?2000.:18000.;
 float aa=.5*fwidth(h),effective=sqrt(width*width+aa*aa);
 float profile=exp(-.5*pow(h/effective,2.))*width/effective;
 // Evaluate derivatives before divergent exits; invalid weights preserve input.
 bool legacyVisible=profile>.00001;
 if(t<=0.||(!legacyVisible&&!newOn))return;
 float hit=t-sqrt(max(0.,1.-impact*impact)/a);
 vec3 p=impact<1.?o+max(0.,hit)*d:closest;
 vec3 normal=normalize(p*shape);
 float x=clamp((dot(normal,normalize(czm_sunDirectionWC))+.104528)/.209056,0.,1.);
 float day=x*x*x*(x*(6.*x-15.)+10.);
 float blue=blueOn&&legacyVisible?.16*profile*day:0.,warm=warmOn&&legacyVisible?.12*profile*(1.-day):0.;
 vec3 result=linearRGB(original.rgb)*(1.-blue-warm)+linearRGB(vec3(.34,.46,.59))*blue+linearRGB(vec3(.46,.40,.32))*warm;
 if(newOn)result+=newGlow(o*6371.,normalize(d),normalize(czm_sunDirectionWC));
 out_FragColor=vec4(displayRGB(result),original.a);
}`;
  const stage=viewer.scene.postProcessStages.add(new C.PostProcessStage({name:'earthstudio-approved-soft-rim',fragmentShader,uniforms:{blueOn:()=>settings.blueAtmosphere,warmOn:()=>settings.nightAirglow,newOn:()=>settings.newAirglow,newDensity:()=>settings.newGlowDensity,newThickness:()=>settings.newGlowThickness,newHue:()=>settings.newGlowHue,newSaturation:()=>settings.newGlowSaturation,newBrightness:()=>settings.newGlowBrightness}}));
  stage.enabled=false;
  return {get:()=>({...settings}),set:value=>{settings={...EarthAirglowTransport.defaults,...value,blueAtmosphere:!!value?.blueAtmosphere,nightAirglow:!!value?.nightAirglow,newAirglow:!!value?.newAirglow};stage.enabled=settings.blueAtmosphere||settings.nightAirglow||settings.newAirglow;viewer.scene.requestRender();}};
 }
 const api={weights,create};if(typeof module!=='undefined')module.exports=api;root.EarthSoftRim=api;
})(globalThis);
