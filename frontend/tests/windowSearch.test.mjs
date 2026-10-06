import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source=readFileSync(new URL("../src/utils/windowSearch.ts",import.meta.url),"utf8");
const { outputText }=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2023}});
const { readWindowStream,validateWindowResponse }=await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

function verifiedResult() {
  return {search_hours:1,candidates_checked:1,
    windows:[{start:"2026-09-21T10:00:00.811735+00:00",end:"2026-09-21T10:15:00.811735+00:00",duration_minutes:15,
      verification:{status:"passed",checked_launches:181,max_launch_gap_seconds:5,unsafe_launches:0,duration_seconds:900,
        endpoints_checked:true,horizon_checked:true,duration_checked:true,coverage_checked:true}}],
    diagnostics:{request_id:"test-request",status:"complete",phase:"complete",elapsed_seconds:1,
      returned_windows:1,verification_step_seconds:5,checked_launch_samples:181,clear_launch_samples:181,obstructed_launch_samples:0,
      search_start_utc:"2026-09-21T10:00:00.811735+00:00",search_end_utc:"2026-09-21T11:00:00.811735+00:00"}};
}

function stream(text,chunkSize=7) {
  const bytes=new TextEncoder().encode(text);
  return new Response(new ReadableStream({start(controller){
    for(let offset=0;offset<bytes.length;offset+=chunkSize) controller.enqueue(bytes.slice(offset,offset+chunkSize));
    controller.close();
  }}),{headers:{"content-type":"text/event-stream"}});
}

test("fragmented SSE progress, heartbeat and final verified result are parsed",async()=>{
  const result=verifiedResult();
  const progress={request_id:"test-request",status:"running",phase:"window_validation"};
  const body=`event: progress\r\ndata: ${JSON.stringify(progress)}\r\n\r\n: still working\r\n\r\nevent: result\r\ndata: ${JSON.stringify(result)}\r\n\r\n`;
  const seen=[];
  assert.deepEqual(await readWindowStream(stream(body,1),p=>seen.push(p)),result);
  assert.deepEqual(seen,[progress]);
});

test("error event is incomplete, never a successful empty result",async()=>{
  await assert.rejects(readWindowStream(stream('event: error\ndata: {"detail":"Prediction failed"}\n\n'),()=>{}),/Prediction failed/);
});

test("a truncated stream cannot accept partial verification",async()=>{
  await assert.rejects(readWindowStream(stream('event: progress\ndata: {"phase":"complete"}\n\n'),()=>{}),/ended before verification completed/);
});

test("a backend without a progress endpoint cannot silently supply unchecked windows",async()=>{
  await assert.rejects(readWindowStream(new Response('{}',{headers:{"content-type":"application/json"}}),()=>{}),/did not open a progress stream/);
});

test("non-success HTTP errors retain the server's explanation",async()=>{
  await assert.rejects(readWindowStream(new Response('{"detail":"Invalid mission"}',{status:422}),()=>{}),/Invalid mission/);
});

for(const [name,mutate] of [
  ["missing coverage report",r=>delete r.windows[0].verification],
  ["incomplete search",r=>r.diagnostics.status="incomplete"],
  ["inconsistent sample counts",r=>r.diagnostics.clear_launch_samples=180],
  ["negative sample counts",r=>{r.diagnostics.checked_launch_samples=-2;r.diagnostics.clear_launch_samples=-1;r.diagnostics.obstructed_launch_samples=-1;}],
  ["unsafe launch",r=>r.windows[0].verification.unsafe_launches=1],
  ["unchecked endpoint",r=>r.windows[0].verification.endpoints_checked=false],
  ["missing launch samples",r=>r.windows[0].verification.checked_launches=180],
  ["excessive launch gap",r=>r.windows[0].verification.max_launch_gap_seconds=10],
  ["invalid duration",r=>r.windows[0].duration_minutes=16],
  ["outside requested horizon",r=>r.diagnostics.search_start_utc="2026-09-21T10:01:00Z"],
]) test(`client rejects ${name}`,()=>{const result=verifiedResult();mutate(result);assert.throws(()=>validateWindowResponse(result));});

test("a completed search with no qualifying window has valid diagnostics",()=>{
  const result=verifiedResult();result.windows=[];result.diagnostics.returned_windows=0;
  assert.equal(validateWindowResponse(result),result);
});
