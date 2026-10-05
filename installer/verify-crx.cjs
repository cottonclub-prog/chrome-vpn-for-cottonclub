// Verify CRX3 developer proof using Chromium's signed-data format.
const fs = require('node:fs');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const bytes = fs.readFileSync(process.argv[2]);
assert.equal(bytes.toString('ascii',0,4),'Cr24');
assert.equal(bytes.readUInt32LE(4),3);
const end = 12 + bytes.readUInt32LE(8);
assert.ok(end < bytes.length);
function fields(buffer) {
  let offset = 0;
  function number() { let value=0, shift=0, byte; do { assert.ok(offset<buffer.length && shift<35); byte=buffer[offset++]; value+=(byte&127)*2**shift; shift+=7; } while(byte&128); return value; }
  const result = [];
  while (offset < buffer.length) {
    const tag=number(); assert.equal(tag&7,2);
    const length=number(); assert.ok(offset+length<=buffer.length);
    result.push([Math.floor(tag/8),buffer.subarray(offset,offset+length)]); offset+=length;
  }
  return result;
}
const header=fields(bytes.subarray(12,end));
const signed=header.find(([tag])=>tag===10000)[1];
const idBytes=fields(signed).find(([tag])=>tag===1)[1];
const signedLength=Buffer.alloc(4); signedLength.writeUInt32LE(signed.length);
const payload=Buffer.concat([Buffer.from('CRX3 SignedData\0'),signedLength,signed,bytes.subarray(end)]);
let verified=false;
for(const [tag,proof] of header.filter(([tag])=>tag===2||tag===3)) {
  const parts=fields(proof), pub=parts.find(([tag])=>tag===1)[1], signature=parts.find(([tag])=>tag===2)[1];
  if(!crypto.createHash('sha256').update(pub).digest().subarray(0,16).equals(idBytes))continue;
  verified=crypto.verify('sha256',payload,crypto.createPublicKey({key:pub,format:'der',type:'spki'}),signature);
  if(verified)break;
}
assert.ok(verified,'CRX developer signature is invalid');
const id=idBytes.toString('hex').replace(/[0-9a-f]/g,c=>String.fromCharCode(97+parseInt(c,16)));
if(process.argv[3])assert.equal(id,process.argv[3],'CRX identity mismatch');
console.log('Verified CRX3 signature and ID: '+id);
