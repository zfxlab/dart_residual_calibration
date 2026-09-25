"""Opt-in real Chrome test: RUN_BROWSER_TESTS=1 python -m unittest ..."""

import os
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

from websockets.sync.client import connect

from backend.server import Handler, ROOT, ThreadingHTTPServer

SMOKE = r"""
async function smokeWait(predicate) {
  for(let i=0;i<300;i++){if(predicate())return;await new Promise(r=>setTimeout(r,50));}
  throw Error('Timed out waiting for UI: '+$('notice').textContent+'; row='+JSON.stringify(current()?.rows[0])+'; dialog='+$('text-dialog').returnValue);
}
async function smokeRun() {
  try {
    $('demo').click();
    await smokeWait(()=>$('chart').data?.length);
    await new Promise(r=>setTimeout(r,200));
    if($('stat-rows').textContent!=='240')throw Error('Demo rows missing');
    for(const id of ['reset-selection','summary','x-min','x-max','filter-field','fit-source','save-template','template-choice']) if($(id))throw Error('Removed control remains: '+id);
    if($('chart').layout.dragmode!=='zoom')throw Error('Chart still selects boxes');
    setView('fit');
    if(!$('data-page').hidden || $('fit-page').hidden || !$('live-panel').hidden) throw Error('Fit page not separated');
    if($('data-page').contains($('model-panel'))) throw Error('Model controls still in data page');
    $('fit-x').value='input'; $('fit-y').value='response';
    $('model').value='quadratic';$('model').dispatchEvent(new Event('change'));
    await smokeWait(()=>document.querySelector('[data-parameter="c"]'));
    $('fit').click();await smokeWait(()=>fitResult!==null);
    if(fitResult.train.count!==192 || fitResult.validation.count!==48)throw Error('Wrong fit split');
    setView('capture');
    if(!$('data-page').hidden || !$('fit-page').hidden || $('capture-panel').hidden) throw Error('Capture page not separated');
    setView('fit');
    if(!fitResult || $('fit-x').value!=='input') throw Error('Fit state lost across navigation');
    setView('explore');
    const cell=$('table').querySelector('td[data-row="0"][data-col="2"]');
    cell.click();
    const editor=cell.querySelector('input');if(!editor)throw Error('Single-click editor missing');
    editor.value='3.5';editor.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
    await smokeWait(()=>current().rows[0].response===3.5);
    if(fitResult!==null)throw Error('Stale fit not cleared');
    // Native dialog close events are queued with rendering; do not reopen in the same frame.
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    const main=state.active;
    addDataset('第二数据集',['x','y'],[{x:1,y:2}],'test');
    state.active=main;render(true);
    await saveDerived('difference','[response]-[input]','m');
    if(Math.abs(current().rows[0].difference-2.5)>1e-8)throw Error('Derived column incorrect');
    const changed=current().rows.map(r=>({...r}));changed[0].input=2;
    await updateDataset(current(),changed);
    if(Math.abs(current().rows[0].difference-1.5)>1e-8)throw Error('Derived column not recomputed');
    setView('fit');
    $('fit-x').value='input';$('fit-y').value='difference';
    $('model').value='custom';$('custom-formula').value='a+b*x+c*x**2';
    await identifyParameters();await runFit();
    if(!fitResult || fitResult.model!=='custom')throw Error('Custom expression fit failed');
    if(document.querySelector('#fit-chart .gl-container canvas'))throw Error('WebGL trace created');
    if(document.createElement('canvas').getContext('webgl'))throw Error('WebGL was not disabled');
    if(document.querySelector('[data-value="lower"],[data-value="upper"],[data-value="fixed"]'))throw Error('Parameter constraints remain');
    setView('explore');
    $('chart').emit('plotly_click',{points:[{customdata:201}]});
    if(activePoint?.index!==201||page!==5||$('point-panel').hidden)throw Error('Point was not located');
    $('point-toggle').click();
    if(!excludedRows().has(201)||fitResult!==null||fitPayload().rows.length!==239)throw Error('Point exclusion did not invalidate fit');
    await smokeWait(()=>$('chart').data[1]?.customdata.includes(201));
    setView('fit');await runFit();
    if(fitResult.train.count+fitResult.validation.count!==239)throw Error('Excluded point reached fit');
    setView('explore');
    $('chart').emit('plotly_click',{points:[{customdata:201,curveNumber:1}]});
    $('point-toggle').click();
    if(excludedRows().size||fitPayload().rows.length!==240)throw Error('Point restore failed');
    // Persist one excluded point in the exported/imported project.
    togglePoint(201);
    setView('fit');
    $('compare-models').click();
    await smokeWait(()=>$('comparison-table').querySelectorAll('tbody tr').length===7);
    setView('explore');
    $('chart-type').value='histogram';$('chart-type').dispatchEvent(new Event('change'));
    await smokeWait(()=>$('chart').data?.[0].type==='histogram');
    if(!localStorage.getItem(KEY))throw Error('Project not persisted');

    // Project identity, download filenames, deletion/cancellation/undo and old imports.
    $('rename-project').click();$('dialog-input').value='温度实验 A';$('text-dialog').close('ok');
    await smokeWait(()=>state.name==='温度实验 A');
    if(JSON.parse(localStorage.getItem(KEY)).name!==state.name)throw Error('Project name not persisted');
    const originalDownload=download, exported=[];
    download=(name,content)=>exported.push({name,content});
    $('save-project').click();
    if(exported[0].name!=='温度实验 A.json'||JSON.parse(exported[0].content).name!==state.name)throw Error('Project filename wrong');
    $('export-csv').click();
    if(exported[1].name!==current().name+'.csv')throw Error('CSV name changed');
    download=originalDownload;
    const savedProject=JSON.parse(exported[0].content);
    async function removeData(id, confirm=true) {
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      const done=deleteDataset(id);$('delete-dialog').close(confirm?'delete':'cancel');await done;
    }
    const active=state.active, other=state.datasets.find(d=>d.id!==active), count=state.datasets.length;
    await removeData(other.id,false);
    if(state.datasets.length!==count)throw Error('Cancelled deletion changed data');
    await removeData(other.id);
    if(state.active!==active||state.datasets.length!==count-1)throw Error('Nonactive deletion changed active dataset');
    undoDelete();
    if(state.active!==other.id||state.datasets.length!==count)throw Error('Undo failed');
    await removeData(state.active);
    if(!current())throw Error('Active deletion did not select remaining dataset');
    while(state.datasets.length)await removeData(state.datasets[0].id);
    if(current()||state.active!==null||!$('fit').disabled||!$('export-csv').disabled)throw Error('Empty project state invalid');
    if(JSON.parse(localStorage.getItem(KEY)).datasets.length!==0)throw Error('Deletion not persisted');
    await importProject(savedProject,'saved.json');
    if(state.name!=='温度实验 A'||state.datasets.length!==count)throw Error('Project import lost identity');
    if(!excludedRows().has(201)||fitPayload().rows.length!==239)throw Error('Project lost exclusions');
    const importedCount=state.datasets.length;
    await importProject({version:1,name:'另一个项目',datasets:[{id:'old',name:'追加',columns:['x','y'],rows:[{x:1,y:2}]}]},'other.json');
    if(state.name!=='温度实验 A'||state.datasets.length!==importedCount+1)throw Error('Merge overwrote project name');
    while(state.datasets.length)await removeData(state.datasets[0].id);
    await importProject({version:1,datasets:[{id:'v1',name:'旧数据',columns:['x','y'],rows:[{x:1,y:2}]}]},'旧项目.json');
    if(state.name!=='旧项目')throw Error('Legacy project name migration failed');
    if(exportFilename('a/b:c','json')!=='a_b_c.json')throw Error('Invalid filename not sanitized');


    // Table-first layout, ordered lines, original row identity and direct column fitting.
    const probe=addDataset('乱序样例',['x','y'],[{x:3,y:30},{x:1,y:10},{x:2,y:20}],'test');
    setView('explore');
    if(!(document.querySelector('.table-card').compareDocumentPosition(document.querySelector('.plot-card')) & Node.DOCUMENT_POSITION_FOLLOWING))throw Error('Table is not above chart');
    $('chart-type').value='line';$('chart-type').dispatchEvent(new Event('change'));
    await smokeWait(()=>$('chart').data?.[0].mode==='lines+markers');
    if(JSON.stringify($('chart').data[0].x)!=='[1,2,3]' || JSON.stringify($('chart').data[0].customdata)!=='[1,2,0]')throw Error('Line order/row identity incorrect');
    if(probe.rows[0].x!==3)throw Error('Plot sorted original records');
    await saveDerived('twice','[y]*2');
    setView('fit');
    if($('fit-x').tagName!=='SELECT'||!Array.from($('fit-y').options).some(o=>o.value==='twice'))throw Error('Derived column missing in selector');
    $('fit-x').value='x';$('fit-y').value='twice';
    if(fitPayload().y!=='twice')throw Error('Column choice not passed to fit');
    setView('explore');
    await deleteTableItem('column',1);
    if($('table-delete-dialog').open||!probe.columns.includes('y'))throw Error('Dependent column deletion allowed');
    async function removeItem(kind,index,confirm=true) {
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      const done=deleteTableItem(kind,index);
      if(!$('table-delete-dialog').open)throw Error('Delete confirmation missing');
      $('table-delete-dialog').close(confirm?'delete':'cancel');await done;
    }
    await removeItem('column',2,false);
    if(!probe.columns.includes('twice'))throw Error('Cancelled column deletion changed data');
    await removeItem('column',2);
    if(probe.columns.includes('twice')||probe.derived.length||$('fit-y').value==='twice')throw Error('Deleted derived field remained');
    togglePoint(2);renderRecords();
    $('table').querySelector('[data-delete-row="1"]').click();
    $('table-delete-dialog').close('delete');
    await smokeWait(()=>probe.rows.length===2);
    if(probe.rows.some(r=>r.x===1)||!excludedRows().has(1)||excludedRows().has(2))throw Error('Row deletion did not remap exclusions');
    await removeItem('column',1);
    if(!excludedRows().has(1))throw Error('Column deletion lost exclusions');
    if(probe.rows.some(r=>Object.hasOwn(r,'y'))||probe.columns.length!==1)throw Error('Column values survived deletion');
    await deleteTableItem('column',0);
    if(probe.columns.length!==1)throw Error('Last field deleted');
    while(probe.rows.length)await removeItem('row',0);
    if(excludedRows().size)throw Error('Deleted records left stale exclusions');
    $('add-row').click();await smokeWait(()=>probe.rows.length===1);
    const newCell=$('table').querySelector('td.editable');newCell.click();
    const blankEditor=newCell.querySelector('input');blankEditor.value='42';blankEditor.dispatchEvent(new Event('blur'));
    await smokeWait(()=>probe.rows[0].x===42);
    if(JSON.parse(localStorage.getItem(KEY)).datasets.find(d=>d.id===probe.id).rows[0].x!==42)throw Error('Edited row not persisted');
    // Stopped capture summaries use the real API but synthetic ROS-free samples.
    async function fixture(id, rows, running=false) {
      await smokeWait(()=>!pollBusy);
      await api('/test/capture', {id,rows,running});
      await pollCapture();
    }
    const chosenDataset=addDataset('当前工况表',['manual_note'],[],'手工记录');
    setView('capture');
    await fixture('capture-zero',[
      {temperature:0,pressure:2,status:1}, {temperature:2,pressure:4,status:1},
      {temperature:999,pressure:8,status:0}, {temperature:null,pressure:6,status:1}
    ],true);
    if(!$('calculate-capture-summary').disabled||$('capture-summary-panel').hidden)throw Error('Running summary UI invalid');
    await fixture('capture-zero',captureData.samples);
    if($('capture-summary-mode')||$('capture-summary-x')||$('capture-summary-z'))throw Error('Direction-specific controls remain');
    for(const o of $('capture-summary-fields').options)o.selected=['temperature','pressure'].includes(o.value);
    $('capture-summary-fields').dispatchEvent(new Event('change'));
    $('capture-summary-valid').value='status';$('capture-summary-valid').dispatchEvent(new Event('change'));
    await calculateCaptureSummary();
    let temp=captureSummary.statistics.find(s=>s.field==='temperature');
    if(temp.mean!==1||temp.count!==2||temp.min!==0)throw Error('Generic statistics wrong');
    const referenceRow = name => Array.from($('capture-reference-list').children).find(row=>row.querySelector('.reference-name').value===name);
    const setReference = (name,value) => referenceRow(name).querySelector('.reference-value').value=String(value);
    $('generate-capture-references').click();$('generate-capture-references').click();
    if($('capture-reference-list').children.length!==2)throw Error('Generated duplicate reference fields');
    $('capture-summary-name').value='工况 A';setReference('temperature_ref',0);setReference('pressure_ref',101);
    referenceRow('temperature_ref').querySelector('.reference-unit').value='°C';
    referenceRow('temperature_ref').querySelector('.reference-unit').dispatchEvent(new Event('input',{bubbles:true}));
    const pressureName=referenceRow('pressure_ref').querySelector('.reference-name');
    pressureName.value='temperature_ref';await saveCaptureSummary();
    if(chosenDataset.rows.length)throw Error('Duplicate reference names saved');
    pressureName.value='pressure_mean';await saveCaptureSummary();
    if(chosenDataset.rows.length)throw Error('Reference overwrote statistics');
    pressureName.value='pressure_ref';
    $('add-capture-reference').click();
    const custom=$('capture-reference-list').lastElementChild;
    custom.querySelector('.reference-name').value='yaw_ref_deg';custom.querySelector('.reference-unit').value='deg';
    custom.querySelector('.reference-name').dispatchEvent(new Event('input',{bubbles:true}));
    $('add-capture-reference').click();$('capture-reference-list').lastElementChild.querySelector('.remove-reference').click();
    if($('capture-reference-list').children.length!==3)throw Error('Reference deletion failed');
    await saveCaptureSummary();
    const summaryDataset=current();
    if(summaryDataset!==chosenDataset)throw Error('Summary not appended to selected dataset');
    if(Object.keys(summaryDataset.rows[0]).some(k=>['capture_id','created_at','topic','summary_key','sample_mode','valid_field','total_count'].includes(k)))throw Error('Summary metadata leaked into record');
    if(summaryDataset.rows[0].temperature_mean!==1||summaryDataset.rows[0].temperature_ref!==0||summaryDataset.rows[0].pressure_ref!==101||summaryDataset.rows[0].yaw_ref_deg!==null||summaryDataset.column_units.temperature_ref!=='°C')throw Error('Generic record not saved');
    await saveCaptureSummary();
    if(summaryDataset.rows.length!==1)throw Error('Duplicate summary saved');
    $('capture-summary-value').value='0';$('capture-summary-value').dispatchEvent(new Event('change'));
    if(captureSummary||!$('save-capture-summary').disabled)throw Error('Changed condition retained old result');
    $('capture-summary-value').value='1';$('capture-summary-value').dispatchEvent(new Event('change'));
    await fixture('capture-invalid',[{temperature:null,pressure:null,status:1}]);
    if(captureSummary)throw Error('New capture retained old result');
    if(Array.from($('capture-reference-list').querySelectorAll('.reference-value')).some(input=>input.value!==''))throw Error('New capture retained reference values');
    if(!referenceRow('pressure_ref')||referenceRow('temperature_ref').querySelector('.reference-unit').value!=='°C')throw Error('New capture lost reference configuration');
    await calculateCaptureSummary();
    if(captureSummary.statistics.some(s=>s.mean!==null))throw Error('Invalid values not null');
    $('capture-summary-name').value='空数据';await saveCaptureSummary();
    if(summaryDataset.rows.length!==2||summaryDataset.rows[1].temperature_mean!==null)throw Error('Null summary not saved');
    for(const value of [10,20,30,40]) {
      await fixture('capture-'+value,[{temperature:value,pressure:value*3,status:1}]);
      await calculateCaptureSummary();
      $('capture-summary-name').value='工况 '+value;setReference('temperature_ref',value*2+1);setReference('pressure_ref',value*3+1);
      await saveCaptureSummary();
    }
    const restored=JSON.parse(localStorage.getItem(KEY)).datasets.find(d=>d.id===summaryDataset.id);
    if(restored.rows.length!==6||restored.rows[1].temperature_mean!==null||restored.rows[1].pressure_ref!==null||restored.rows[5].pressure_ref!==121)throw Error('Summary persistence broken');
    const savedReferenceConfig=JSON.parse(localStorage.getItem(KEY)).captureReferenceFields;
    if(savedReferenceConfig.length!==3||savedReferenceConfig.some(item=>Object.hasOwn(item,'value')))throw Error('Reference configuration persistence incorrect');
    state.active=summaryDataset.id;render(true);setView('fit');
    $('fit-x').value='temperature_mean';$('fit-y').value='temperature_ref';$('validation').value='0';$('model').value='linear';
    await identifyParameters();await runFit();
    if(!fitResult||fitResult.train.count!==5||fitResult.skipped!==1)throw Error('Summary cannot fit or empty row not skipped');
    setView('capture');await pollCapture();
    $('live-field').value='temperature';drawLive();
    await smokeWait(()=>$('live-chart').querySelector('.ytitle'));
    const titleBox=$('live-chart').querySelector('.ytitle').getBoundingClientRect();
    const tickBoxes=Array.from($('live-chart').querySelectorAll('.ytick text'),t=>t.getBoundingClientRect());
    if(tickBoxes.some(b=>titleBox.right>b.left-2))throw Error('Live Y title overlaps tick labels');
    const otherTarget=addDataset('另一个工况表',['note'],[],'test');
    await saveCaptureSummary();
    if(otherTarget.rows.length!==1||summaryDataset.rows.length!==6)throw Error('Saving ignored changed active dataset');
    state.active=null;render();
    await saveCaptureSummary();
    if(current()?.name!=='采集汇总记录'||current().rows.length!==1)throw Error('Empty workspace summary fallback failed');
    const realApi=api,realConfirm=window.confirm;let starts=0;
    window.confirm=()=>{throw Error('Unexpected new capture confirmation')};
    api=async(path,body)=>path==='/api/capture/start'?(starts++,{ok:true}):realApi(path,body);
    await $('start-capture').onclick();
    api=realApi;window.confirm=realConfirm;
    if(starts!==1)throw Error('New capture did not start directly');
    document.body.dataset.smoke='passed';
  } catch(error) {document.body.dataset.smoke='failed: '+error.stack;}
}
smokeRun();
"""


class SmokeHandler(Handler):
    def do_POST(self):
        if self.path == "/test/capture":
            fixture = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            type(self).capture = SimpleNamespace(
                id=fixture["id"], topic="/test/ray", running=fixture["running"],
                snapshot=lambda: (fixture["rows"], [], None))
            return self.reply({"ok": True})
        return super().do_POST()

    def do_GET(self):
        if self.path == "/app.js":
            return self.reply((ROOT / "js" / "app.js").read_bytes() + SMOKE.encode(), mime="text/javascript")
        return super().do_GET()


@unittest.skipUnless(os.environ.get("RUN_BROWSER_TESTS") == "1", "opt-in Chrome UI test")
class BrowserTests(unittest.TestCase):
    def test_point_exclusion_fit_edit_and_project(self):
        with tempfile.TemporaryDirectory(prefix="workbench-chrome-") as profile:
            server = ThreadingHTTPServer(("127.0.0.1", 0), SmokeHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                process = subprocess.Popen([
                    "/opt/google/chrome/chrome", "--headless", "--no-sandbox", "--disable-gpu", "--disable-webgl",
                    "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check",
                    f"--user-data-dir={profile}", "--remote-debugging-port=0", "about:blank",
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    deadline = time.monotonic() + 30
                    port_file = Path(profile) / "DevToolsActivePort"
                    while not port_file.exists() and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertTrue(port_file.exists(), "Chrome failed to start")
                    port = int(port_file.read_text().splitlines()[0])
                    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
                        target = next(t for t in json.load(response) if t["type"] == "page")
                    with connect(target["webSocketDebuggerUrl"], max_size=10_000_000) as socket:
                        sequence = 0

                        def command(method, params):
                            nonlocal sequence
                            sequence += 1
                            socket.send(json.dumps({"id": sequence, "method": method, "params": params}))
                            while True:
                                result = json.loads(socket.recv(timeout=10))
                                if result.get("id") == sequence:
                                    return result

                        command("Page.navigate", {"url": f"http://127.0.0.1:{server.server_port}"})
                        marker = None
                        while time.monotonic() < deadline:
                            result = command("Runtime.evaluate", {"expression": "document.body?.dataset.smoke", "returnByValue": True})
                            marker = result.get("result", {}).get("result", {}).get("value")
                            if marker:
                                break
                            time.sleep(.1)
                        self.assertEqual(marker, "passed")
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
