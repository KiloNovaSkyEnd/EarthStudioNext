/* R3 finite-path display approximation. Same 3 layers/12-point quadrature as Blender. */
(function(root){
const glsl=`
uniform bool newOn;
uniform float newDensity;
uniform float newThickness;
uniform float newHue;
uniform float newSaturation;
uniform float newBrightness;
float glowErf(float x){return tanh(1.128379167*x+.1*x*x*x);}
vec3 glowHSV(vec3 rgb){
 float hi=max(rgb.r,max(rgb.g,rgb.b)),lo=min(rgb.r,min(rgb.g,rgb.b)),delta=hi-lo,h=0.;
 if(delta>1.e-10){if(hi==rgb.r)h=mod((rgb.g-rgb.b)/delta,6.);else if(hi==rgb.g)h=(rgb.b-rgb.r)/delta+2.;else h=(rgb.r-rgb.g)/delta+4.;h/=6.;}
 h=fract(h+newHue/360.);float s=hi>0.?delta/hi:0.;s=clamp(s*newSaturation,0.,1.);
 vec3 basis=clamp(abs(fract(h+vec3(0.,2./3.,1./3.))*6.-3.)-1.,0.,1.);
 return hi*newBrightness*mix(vec3(1.),basis,s);
}
vec3 glowLayer(vec3 closest,vec3 direction,vec3 sun,float impact,float cam,float lower,float base,float scale,float height,float sigma,float gain,vec3 color){
 const float gx[12]=float[12](-.9815606342,-.9041172564,-.7699026742,-.5873179543,-.3678314989,-.1252334085,.1252334085,.3678314989,.5873179543,.7699026742,.9041172564,.9815606342);
 const float gw[12]=float[12](.0471753364,.106939326,.1600783285,.2031674267,.2334925365,.2491470458,.2491470458,.2334925365,.2031674267,.1600783285,.106939326,.0471753364);
 sigma*=clamp(newThickness,.5,2.);float lo=6371.+max(0.,height-4.*sigma),hi=6371.+height+4.*sigma;
 float slo=sqrt(max(0.,lo*lo-impact*impact)),shi=sqrt(max(0.,hi*hi-impact*impact));vec3 total=vec3(0.);
 for(int side=0;side<2;side++){
  float start=max(side==0?slo:-shi,lower),end=max(start,min(side==0?shi:-slo,cam));float halfRange=.5*(end-start),mid=.5*(end+start);
  for(int j=0;j<12;j++){
   float s=mid+gx[j]*halfRange,altitude=sqrt(impact*impact+s*s)-6371.;vec3 pos=closest-direction*s;
   float z=(altitude-height)/sigma,u=clamp((.02-dot(normalize(pos),sun))/.32,0.,1.);float night=u*u*u*(u*(6.*u-15.)+10.);
   float strength=exp(-.5*z*z)*night*gw[j]*gain*halfRange;
   float column=max(0.,base*(glowErf(cam/scale)-glowErf(s/scale)));
   total+=color*exp(-vec3(.005802,.013558,.033100)*column)*strength;
  }
 }
 return total;
}
vec3 newGlow(vec3 origin,vec3 direction,vec3 sun){
 float cam=-dot(origin,direction);if(cam<=0.)return vec3(0.);
 vec3 closest=origin+direction*cam;float impact=length(closest),height=impact-6371.;if(height>520.)return vec3(0.);
 float ground=sqrt(max(0.,6371.*6371.-impact*impact));float lower=impact<6371.&&cam>ground?ground:-10000.;
 float scale=sqrt(16.*max(6371.,impact));float base=exp(-max(-1.,height)/8.)*sqrt(3.141592653589793*4.*max(6371.,impact));
 vec3 rgb=glowLayer(closest,direction,sun,impact,cam,lower,base,scale,98.,8.,1.6e-5,vec3(.24,1.,.035));
 rgb+=glowLayer(closest,direction,sun,impact,cam,lower,base,scale,90.,5.,8.e-6,vec3(1.,.57,.015));
 rgb+=glowLayer(closest,direction,sun,impact,cam,lower,base,scale,240.,35.,1.1e-6,vec3(1.,.018,.004));
 return glowHSV(rgb*newDensity);
}
`;
const api={glsl,defaults:{newAirglow:false,newGlowDensity:1,newGlowThickness:1,newGlowHue:0,newGlowSaturation:1,newGlowBrightness:1}};
if(typeof module!=='undefined')module.exports=api;root.EarthAirglowTransport=api;
})(globalThis);
