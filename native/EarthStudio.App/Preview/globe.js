'use strict';
// Direct stock Satpy display pixels; missing observations remain neutral grey.
const canvas = document.getElementById('globe');
const state = document.getElementById('state');
const gl = canvas.getContext('webgl', {antialias: true, alpha: false});
if (!gl) { state.textContent = 'WebGL 不可用'; throw new Error('WebGL unavailable'); }
const vertex = 'attribute vec2 p; varying vec2 v; void main(){v=p;gl_Position=vec4(p,0.,1.);}';
const fragment = `precision highp float;
varying vec2 v; uniform vec2 resolution; uniform vec3 camera,right,up;
uniform sampler2D surface; uniform bool loaded,source_linear,rim_enabled;
uniform vec3 sun_direction;
vec3 linear_rgb(vec3 c){return mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));}
vec3 srgb(vec3 c){c=max(c,vec3(0.));return mix(12.92*c,1.055*pow(c,vec3(1./2.4))-.055,step(vec3(.0031308),c));}
vec3 view_ray(vec2 pixel){
 vec2 q=pixel*vec2(resolution.x/resolution.y,1.);
 vec3 forward=normalize(-camera);
 return normalize(forward+q.x*right*.47+q.y*up*.47);
}
vec3 sample_scene(vec3 ray){
 float b=dot(camera,ray),c=dot(camera,camera)-1.,d=b*b-c;
 vec3 color=vec3(0.);
 vec3 point=camera+ray*max(-b,0.);
 if(d>0.){
  float t=-b-sqrt(d);
  if(t>0.){
   point=camera+t*ray; vec3 n=normalize(point);
   // Right-handed Y-up world: east longitude points toward -Z.
   // Using +atan(z,x) mirrors the map through every camera's north axis.
   vec2 uv=vec2(.5-atan(n.z,n.x)/6.2831853,asin(clamp(n.y,-1.,1.))/3.14159265+.5);
   vec4 weather=loaded?texture2D(surface,uv):vec4(0.);
   color=mix(linear_rgb(vec3(.09)),source_linear?weather.rgb:linear_rgb(weather.rgb),weather.a);
  }
 }
 if(rim_enabled && b<0.){
  float h=(length(cross(camera,ray))-1.)*6371.;
  float width=h<0.?2.:18.; float profile=exp(-.5*pow(h/width,2.));
  float t=clamp((dot(normalize(point),sun_direction)+.104528)/.209056,0.,1.);
  float day=t*t*t*(t*(6.*t-15.)+10.);
  float blue=.16*profile*day,warm=.12*profile*(1.-day);
  color=color*(1.-blue-warm)+linear_rgb(vec3(.34,.46,.59))*blue+linear_rgb(vec3(.46,.40,.32))*warm;
 }
 return color;
}
void main(){
 vec3 ray=view_ray(v),color=vec3(0.);
 float h=(length(cross(camera,ray))-1.)*6371.;
 if(abs(h)<60.){
  for(int y=0;y<4;y++)for(int x=0;x<4;x++)
   color+=sample_scene(view_ray(v+((vec2(float(x),float(y))+.5)/4.-.5)*2./resolution));
  color/=16.;
 }else color=sample_scene(ray);
 gl_FragColor=vec4(srgb(color),1.);
}`;
function shader(type, source) {
 const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);
 if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;
}
const program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,vertex));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);
if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program));
gl.useProgram(program);
const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
const attribute=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(attribute);gl.vertexAttribPointer(attribute,2,gl.FLOAT,false,0,0);
const uniforms={};for(const name of ['resolution','camera','right','up','surface','loaded','source_linear','rim_enabled','sun_direction'])uniforms[name]=gl.getUniformLocation(program,name);
const srgbExtension=gl.getExtension('EXT_sRGB');
const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);
gl.texImage2D(gl.TEXTURE_2D,0,gl.RGB,1,1,0,gl.RGB,gl.UNSIGNED_BYTE,new Uint8Array([20,40,70]));
gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
gl.uniform1i(uniforms.surface,0);
let yaw=-1.92,pitch=.28,distance=3.25,loaded=false,rim=false,sun=[1,0,0];
function draw(){
 const ratio=Math.min(devicePixelRatio||1,1.5),w=Math.round(canvas.clientWidth*ratio),h=Math.round(canvas.clientHeight*ratio);
 if(w<1||h<1)return;
 if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;gl.viewport(0,0,w,h);}
 const cp=Math.cos(pitch),sp=Math.sin(pitch),cy=Math.cos(yaw),sy=Math.sin(yaw);
 gl.uniform2f(uniforms.resolution,w,h);gl.uniform3f(uniforms.camera,distance*cp*cy,distance*sp,distance*cp*sy);
 gl.uniform3f(uniforms.right,sy,0,-cy);gl.uniform3f(uniforms.up,-sp*cy,cp,-sp*sy);
 gl.uniform1i(uniforms.loaded,loaded);gl.uniform1i(uniforms.source_linear,!!srgbExtension);
 gl.uniform1i(uniforms.rim_enabled,rim);gl.uniform3f(uniforms.sun_direction,...sun);gl.drawArrays(gl.TRIANGLES,0,6);
}
let requestId=0;
function loadWeather(url,utc,sunVector,atmosphere){
 const current=++requestId;
 const image=new Image();image.crossOrigin='anonymous';image.onload=()=>{
 if(current!==requestId)return;
 gl.bindTexture(gl.TEXTURE_2D,texture);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
 gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);
 const format=srgbExtension?srgbExtension.SRGB_ALPHA_EXT:gl.RGBA;
 gl.texImage2D(gl.TEXTURE_2D,0,format,format,gl.UNSIGNED_BYTE,image);loaded=true;
 const validSun=Array.isArray(sunVector)&&sunVector.length===3&&sunVector.every(Number.isFinite);
 rim=validSun&&atmosphere;
 if(validSun)sun=[sunVector[0],sunVector[2],-sunVector[1]];
 state.textContent='实测天气 · AHI/ABI GeoColor + SEVIRI 自然色 · 代理预览';
 document.getElementById('time').textContent=utc;
 draw();
 };image.onerror=()=>{if(current===requestId){loaded=false;state.textContent='天气文件不可用；未使用静态地表填补';draw();}};
 image.src=url;
}
let pointer=null;
canvas.addEventListener('pointerdown',e=>{pointer={x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{if(!pointer)return;yaw+=(e.clientX-pointer.x)*.006;pitch=Math.max(-1.45,Math.min(1.45,pitch+(e.clientY-pointer.y)*.006));pointer={x:e.clientX,y:e.clientY};draw();});
canvas.addEventListener('pointerup',()=>pointer=null);canvas.addEventListener('pointercancel',()=>pointer=null);
canvas.addEventListener('wheel',e=>{e.preventDefault();distance=Math.max(1.15,Math.min(7,distance*Math.exp(e.deltaY*.001)));draw();},{passive:false});
canvas.addEventListener('dblclick',()=>{yaw=-1.92;pitch=.28;distance=3.25;draw();});
new ResizeObserver(draw).observe(canvas);
window.chrome?.webview?.addEventListener('message',e=>{
 if(typeof e.data?.weather==='string' && e.data.weather.startsWith('https://legacy-materials.local/'))loadWeather(e.data.weather,e.data.time||'',e.data.sun,e.data.atmosphere===true);
 else if(typeof e.data?.time==='string')document.getElementById('time').textContent=e.data.time+' · 项目时间，未切换天气';
});
draw();
window.chrome?.webview?.postMessage({ready:true});
