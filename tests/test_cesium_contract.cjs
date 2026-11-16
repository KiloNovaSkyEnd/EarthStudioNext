const assert = require('node:assert/strict');
const {validateManifest} = require('../native/EarthStudio.App/Cesium/contract.js');
const frame = {utc:'2026-10-20T22:40:00Z',source:'AHI',recipe:'geo_color',detail:'bounded-sample',kind:'single-image',bounds:[120,10,140,30],path:'sample.png'};
const make = f => ({schema:'earthstudio.materials.v1',earthModel:'WGS84',scope:'regional',frames:[f]});
assert.equal(validateManifest(make(frame)).frames.length,1);
assert.doesNotThrow(() => validateManifest(make({...frame,bounds:[170,-10,-170,10]})));
for (const change of [{path:'../secret.png'},{path:'https://example.com/a.png'},{utc:'yesterday'},{bounds:[0,40,10,20]},{detail:'500m'},{recipe:''},{kind:'geographic-tiles',path:'{z}/{x}/{y}.png'}]) {
  assert.throws(() => validateManifest(make({...frame,...change})));
}
assert.throws(() => validateManifest({...make(frame),frames:[frame,frame]}));
assert.doesNotThrow(() => validateManifest(make({...frame,kind:'geographic-tiles',path:'tiles/{z}/{x}/{y}.png',maximumLevel:8})));
assert.throws(()=>validateManifest(make({...frame,kind:'geographic-tiles',path:'tiles/{z}/{x}/{y}.png',maximumLevel:8,tileSize:0})));
assert.doesNotThrow(()=>validateManifest(make({...frame,kind:'geographic-tiles',path:'tiles/{z}/{x}/{y}.png',maximumLevel:8,tileSize:512})));
console.log('PASS: manifest scope, antimeridian, provenance, UTC ordering, path isolation, real tile levels');
assert.doesNotThrow(()=>validateManifest(make({...frame,previewPath:'scan/preview_4096_abc.png',previewBounds:[-180,-90,180,90]})));
assert.throws(()=>validateManifest(make({...frame,previewPath:'../preview.png',previewBounds:[-180,-90,180,90]})));
assert.throws(()=>validateManifest(make({...frame,previewPath:'preview.png',previewBounds:[0,90,180,-90]})));
