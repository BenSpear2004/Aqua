// Local Chrome DevTools Protocol review. Uses Node's native WebSocket; no packages.
import { spawn } from "node:child_process";
import { mkdir, writeFile, readdir, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const artifactDir = path.join(tmpdir(), "aqua-frontend-review");
await mkdir(artifactDir, { recursive: true });
const profileDir = path.join(artifactDir, `chrome-profile-${Date.now()}`);
const debuggingPort = 19000 + Math.floor(Math.random() * 1000);
const executable = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const browser = spawn(executable, ["--headless=new", `--remote-debugging-port=${debuggingPort}`, `--user-data-dir=${profileDir}`,
  "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "--disable-sync",
  "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
  "--enable-unsafe-swiftshader", "--window-size=1440,900", "about:blank"], { windowsHide: true, stdio: "ignore" });
let launchError;
browser.on("error", (error) => { launchError = error; });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let socket;
const checks = [];
const errors = [];
const warnings = [];
const failureMode = process.argv.includes("--missing-models") ? "missing-models" : process.argv.includes("--no-webgl") ? "no-webgl" : null;
const keepAlive = setInterval(() => {}, 1000);
try {
  let target;
  for (let attempt = 0; attempt < 80; attempt++) {
    if (launchError) throw launchError;
    try { target = (await (await fetch(`http://127.0.0.1:${debuggingPort}/json/list`)).json()).find((item) => item.type === "page"); } catch {}
    if (target) break;
    await sleep(100);
  }
  if (!target) throw new Error("Local Chrome did not expose a review target");
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  const pending = new Map();
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) request?.reject(new Error(message.error.message)); else request?.resolve(message.result);
    }
    if (message.method === "Runtime.exceptionThrown") errors.push(message.params.exceptionDetails);
    if (message.method === "Runtime.consoleAPICalled") {
      const detail = message.params.args.map((arg) => arg.value ?? arg.description).join(" ");
      if (message.params.type === "error") errors.push(detail);
      if (message.params.type === "warning") warnings.push(detail);
    }
  };
  const cdp = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 15000);
    pending.set(id, { resolve: (value) => { clearTimeout(timeout); resolve(value); }, reject: (error) => { clearTimeout(timeout); reject(error); } });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text + " " + (result.exceptionDetails.exception?.description || ""));
    return result.result.value;
  };
  const check = (name, value) => { checks.push({ name, pass: Boolean(value) }); if (!value) throw new Error(`Check failed: ${name}`); };
  const waitFor = async (expression, timeout = 15000) => {
    const start = Date.now();
    while (Date.now() - start < timeout) { if (await evaluate(`Boolean(${expression})`)) return; await sleep(100); }
    await writeFile(path.join(artifactDir,`${failureMode||'normal'}-failed-dom.json`),JSON.stringify(await evaluate("({text:document.body.innerText.slice(0,1500),draft:document.querySelector('textarea')?.value,disabled:document.querySelector('.send-button')?.disabled,messages:document.querySelectorAll('.message').length,forming:document.querySelectorAll('.message--forming').length})"),null,2));
    throw new Error(`Timed out waiting for ${expression}`);
  };
  const screenshot = async (name) => {
    const result = await cdp("Page.captureScreenshot", { format: "png" });
    await writeFile(path.join(artifactDir, `${name}.png`), Buffer.from(result.data, "base64"));
  };
  const clickText = (text) => evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(b => b.textContent.trim() === ${JSON.stringify(text)} && b.getBoundingClientRect().width); if (!b) throw Error('Missing button '+${JSON.stringify(text)}); b.click(); })()`);
  const setInput = (value) => evaluate(`(() => { const t=document.querySelector('textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(t,${JSON.stringify(value)}); t.dispatchEvent(new Event('input',{bubbles:true})); t.focus(); })()`);
  const sendPrompt = async (value) => { await setInput(value); await evaluate("document.querySelector('textarea').form.requestSubmit()"); };
  await Promise.all([cdp("Runtime.enable"), cdp("Page.enable"), cdp("Network.enable")]);
  await cdp("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: artifactDir });
  await cdp("Browser.grantPermissions", { origin: "http://127.0.0.1:5173", permissions: ["clipboardReadWrite", "clipboardSanitizedWrite"] });
  if(failureMode==="missing-models") await cdp("Network.setBlockedURLs",{urls:["*/Aqua_logo.glb","*/Chatbar.glb"]});
  if(failureMode==="no-webgl") await cdp("Page.addScriptToEvaluateOnNewDocument",{source:"const getContext=HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext=function(kind,...args){return String(kind).startsWith('webgl') ? null : getContext.call(this,kind,...args)}"});
  await cdp("Page.navigate", { url: "http://127.0.0.1:5173" });
  await cdp("Page.bringToFront");
  if(failureMode) {
    await waitFor("document.querySelector('textarea') && document.querySelector('.chat-bar-fallback') && document.querySelector('.logo-fallback') && !document.querySelectorAll('canvas').length");
    check(`${failureMode}: graceful fallback at startup`,true);
    await sendPrompt("fallback at startup");
    await waitFor("document.querySelector('.message--aqua') && !document.querySelector('.message--forming')");
    check(`${failureMode}: semantic input and response remain functional`,true);
    await screenshot(`${failureMode}-desktop`);
    await cdp("Emulation.setDeviceMetricsOverride",{width:390,height:844,deviceScaleFactor:1,mobile:false});
    await sleep(200);
    await screenshot(`${failureMode}-mobile`);
    console.log(JSON.stringify({artifactDir,checks,expectedHandledErrors:errors.length,warnings}));
  } else {
  await waitFor("document.querySelector('textarea') && document.querySelectorAll('canvas').length === 2");
  await sleep(2500);
  for (const [width,height,label] of [[1440,900,"desktop"],[1024,768,"tablet"],[390,844,"mobile"]]) {
    await cdp("Emulation.setDeviceMetricsOverride", { width,height,deviceScaleFactor:1,mobile:false });
    await sleep(500);
    check(`${label}: no horizontal page overflow`, await evaluate("document.documentElement.scrollWidth <= innerWidth"));
    await screenshot(`${label}-initial`);
  }
  if (process.argv.includes("--inspect")) {
    console.log(JSON.stringify({ artifactDir, checks, errors, warnings }));
  } else {
    // Interaction and motion checks are maintained below as part of the review.
    await cdp("Emulation.setDeviceMetricsOverride", { width:1440,height:900,deviceScaleFactor:1,mobile:false });
    await sleep(500);
    check("both production GLBs loaded", await evaluate("document.querySelector('.chat-bar-stage--ready') && !document.querySelector('.logo-fallback') && performance.getEntriesByType('resource').filter(r=>/\\.glb($|\\?)/.test(r.name)).length>=2"));
    await clickText("What are my largest expenses?");
    check("FAQ fills and focuses composer", await evaluate("document.querySelector('textarea').value.includes('largest') && document.activeElement.tagName === 'TEXTAREA'"));
    await evaluate(`window.birthFrames=[]; window.bubbleFrames=[]; window.birthStarted=performance.now(); window.rafCount=0;
      window.rafSampler=()=>{window.rafCount++; if(window.rafCount<300)requestAnimationFrame(window.rafSampler)}; requestAnimationFrame(window.rafSampler);
      window.birthSampler=setInterval(()=>{const p=document.querySelector('.message-birth__body');
      const target=document.querySelector('.message--forming .message__bubble');
      window.birthFrames.push({t:performance.now()-window.birthStarted,path:p?.getAttribute('d'),forming:document.querySelectorAll('.message--forming').length,
      visibility:document.visibilityState,rafCount:window.rafCount,svg:document.querySelectorAll('.message-birth').length,aqua:Boolean(document.querySelector('.message-birth--aqua')),target:target?{y:target.getBoundingClientRect().y,height:target.getBoundingClientRect().height}:null});
      window.bubbleFrames.push([...document.querySelectorAll('.thinking-bubble')].map(b=>({x:parseFloat(b.style.left),size:b.getBoundingClientRect().width,
        body:Number(getComputedStyle(b.querySelector('.thinking-bubble__body')).opacity),rim:Number(getComputedStyle(b.querySelector('.thinking-bubble__rim')).opacity)})));},20)`);
    await sendPrompt("multiple tables");
    const birthStarted=Date.now();
    for (const [at,label] of [[90,"bulge"],[300,"attached"],[500,"neck"],[700,"detached"]]) {
      await sleep(Math.max(1,birthStarted+at-Date.now())); await screenshot(`birth-${label}`);
    }
    await sleep(Math.max(1,birthStarted+3500-Date.now()));
    await waitFor("document.querySelectorAll('.financial-table').length === 2 && !document.querySelector('.message--forming')");
    const birthFrames=await evaluate("clearInterval(window.birthSampler); window.birthFrames");
    await writeFile(path.join(artifactDir,"birth-motion.json"),JSON.stringify(birthFrames,null,2));
    const bubbleFrames=await evaluate("window.bubbleFrames");
    await writeFile(path.join(artifactDir,"bubble-motion.json"),JSON.stringify(bubbleFrames,null,2));
    check("physical birth has changing connected SVG outline",birthFrames.filter(f=>f.path?.includes('C')).length>2);
    check("structured AQUA reply forms a manageable connected shell",birthFrames.filter(f=>f.aqua && f.path?.includes('C')).length>2);
    check("birth detaches then semantic message takes over",birthFrames.some(f=>f.path && !f.path.includes('C')) && !birthFrames.at(-1).forming);
    check("bubble body disappears before expanding rim",bubbleFrames.some(f=>f.some(b=>b.body===0 && b.rim>.1)));
    check("bubble pool remains bounded",Math.max(...bubbleFrames.map(f=>f.length))<=12);
    check("at least five waiting bubbles visible",Math.max(...bubbleFrames.map(f=>f.filter(b=>b.body>.3).length))>=5);
    const origins=[...new Set(bubbleFrames.flat().map(b=>Math.round(b.x)))];
    check("bubbles cover five regions across the real bar",origins.length>=5 && Math.max(...origins)-Math.min(...origins)>600);
    check("both tables and KPI results render", await evaluate("document.querySelectorAll('table').length === 2 && document.querySelectorAll('.kpi-card').length === 3"));
    check("charts show semantic axis labels",await evaluate("document.querySelectorAll('.recharts-xAxis').length===2 && document.querySelectorAll('.recharts-yAxis').length===2"));
    await screenshot("desktop-results");
    await evaluate("document.querySelector('.financial-table__scroll').scrollIntoView({block:'center'})");
    await evaluate("document.querySelector('[aria-label=\"Sort by Amount\"]').click()");
    check("table sorts ascending numbers",await evaluate("document.querySelector('tbody tr td:nth-child(2)').textContent==='$27,650' && document.querySelector('th[aria-sort=ascending]')!==null"));
    await evaluate("document.querySelector('[aria-label=\"Sort by Amount\"]').click()");
    check("table sorts descending numbers",await evaluate("document.querySelector('tbody tr td:nth-child(2)').textContent==='$184,200' && document.querySelector('th[aria-sort=descending]')!==null"));
    await clickText("Copy table");
    await waitFor("document.querySelector('.financial-table .action-feedback').textContent.length > 0");
    check("clipboard table action succeeds", await evaluate("document.querySelector('.financial-table .action-feedback').textContent === 'Table copied'"));
    await clickText("Download CSV");
    await waitFor("document.querySelector('.financial-table .action-feedback').textContent === 'CSV downloaded'");
    check("CSV action reports export", await evaluate("document.querySelector('.financial-table .action-feedback').textContent === 'CSV downloaded'"));
    await sleep(200);
    const csvFiles=(await readdir(artifactDir)).filter(name=>name.startsWith('expenses-by-category') && name.endsWith('.csv'));
    check("browser actually downloads Tableau-friendly CSV",csvFiles.length>0 && (await readFile(path.join(artifactDir,csvFiles.at(-1)),"utf8")).includes('"Payroll","184200"'));
    await clickText("Copy response");
    await waitFor("document.querySelector('.response-actions .action-feedback').textContent==='Response copied'");
    check("response copy succeeds",true);
    await evaluate("window.originalClipboard=navigator.clipboard; Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>Promise.reject(new Error('Review denied clipboard'))}})");
    await clickText("Copy table");
    await waitFor("document.querySelector('.financial-table .action-feedback').textContent.includes('unavailable')");
    check("clipboard failure is visible",true);
    await evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:window.originalClipboard})");
    await clickText("Ask a Question");
    check("fresh conversation preserves previous in Recent Chats", await evaluate("!document.querySelector('.message') && document.activeElement.tagName === 'TEXTAREA' && document.body.textContent.includes('multiple tables')"));
    await sendPrompt("error");
    await waitFor("[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Try again')");
    check("error cleans up thinking bubbles",await evaluate("!document.querySelector('.thinking-bubbles')"));
    await clickText("Try again");
    await waitFor("!document.querySelector('.error-card') && !document.querySelector('.message--forming')");
    check("retry does not duplicate user prompt", await evaluate("document.querySelectorAll('.message--user').length === 1"));
    await clickText("Ask a Question");
    await sendPrompt("no data");
    await waitFor("document.body.textContent.includes('No matching financial data') && !document.querySelector('.message--forming')");
    check("no data is readable without empty tables", await evaluate("document.querySelectorAll('table').length === 0"));
    await clickText("Company Analysis");
    check("project folder collapses",await evaluate("document.querySelector('.sidebar-folder').getAttribute('aria-expanded')==='false'"));
    await clickText("Company Analysis");
    await clickText("Operating Costs");
    check("nested project expands",await evaluate("[...document.querySelectorAll('.sidebar-folder')].find(b=>b.textContent.trim()==='Operating Costs').getAttribute('aria-expanded')==='true'"));
    await clickText("Q3 Cash Flow");
    check("project restores its specific conversation",await evaluate("document.querySelector('tbody').rows.length===3 && document.querySelector('.markdown-response').textContent.includes('Q3')"));
    await evaluate("[...document.querySelectorAll('.sidebar-recents button')].find(b=>b.title==='Expense Analysis').click()");
    check("Recent Chats selects centralized record",await evaluate("document.querySelector('tbody').rows.length===5 && document.querySelector('.markdown-response').textContent.includes('Payroll')"));
    await clickText("Ask a Question");
    await sendPrompt("cash flow");
    await clickText("January Review");
    await sleep(2200);
    check("pending reply stays in original chat",await evaluate("document.querySelector('.markdown-response').textContent.includes('January') && !document.querySelector('table') && !document.querySelector('.message-birth')"));
    await evaluate("[...document.querySelectorAll('.sidebar-recents button')].find(b=>b.title==='cash flow').click()");
    check("original pending chat restores completed reply",await evaluate("document.querySelector('tbody').rows.length===6 && document.querySelectorAll('.message--user').length===1"));
    check("line chart renders",await evaluate("Boolean(document.querySelector('.recharts-line'))"));
    await setInput("draft kept in cash flow");
    await clickText("January Review");
    await evaluate("[...document.querySelectorAll('.sidebar-recents button')].find(b=>b.title==='cash flow').click()");
    check("draft survives switching",await evaluate("document.querySelector('textarea').value==='draft kept in cash flow'"));
    await sendPrompt("key metrics");
    await evaluate("document.querySelector('textarea').form.requestSubmit()");
    await waitFor("document.querySelectorAll('.kpi-card').length===3 && !document.querySelector('.message--forming')");
    check("repeated send and request lock prevent duplicates",await evaluate("document.querySelectorAll('.message--user').length===2 && document.querySelectorAll('.message--aqua').length===2"));
    await evaluate("(()=>{const s=document.querySelector('.conversation__scroll'); s.scrollTop=0; s.dispatchEvent(new Event('scroll'))})()");
    await sendPrompt("explain in detail");
    await sleep(2200);
    check("new content preserves position while reading older messages",await evaluate("document.querySelector('.conversation__scroll').scrollTop<2 && !document.querySelector('.message--forming')"));
    await evaluate("(()=>{const s=document.querySelector('.conversation__scroll'); s.scrollTop=s.scrollHeight; s.dispatchEvent(new Event('scroll'))})()");
    await sendPrompt("resize interrupt");
    await sleep(100);
    await cdp("Emulation.setDeviceMetricsOverride",{width:1024,height:768,deviceScaleFactor:1,mobile:false});
    await sleep(150);
    check("resize safely reveals interrupted message",await evaluate("!document.querySelector('.message--forming,.message-birth')"));
    await waitFor("!document.querySelector('.processing-status') && !document.querySelector('.message--forming')");
    await cdp("Emulation.setDeviceMetricsOverride",{width:390,height:844,deviceScaleFactor:1,mobile:false});
    await sleep(350);
    await evaluate("document.querySelector('.sidebar-trigger').click()");
    await waitFor("document.querySelector('[role=dialog]') && document.activeElement.classList.contains('sidebar-close')");
    check("mobile drawer focuses close and inerts background",await evaluate("document.querySelector('.main-panel').inert"));
    await screenshot("mobile-drawer");
    await cdp("Input.dispatchKeyEvent",{type:"keyDown",key:"Tab",code:"Tab",windowsVirtualKeyCode:9,modifiers:8});
    check("drawer traps backward Tab",await evaluate("document.querySelector('[role=dialog]').contains(document.activeElement) && !document.activeElement.classList.contains('sidebar-close')"));
    await cdp("Input.dispatchKeyEvent",{type:"keyDown",key:"Tab",code:"Tab",windowsVirtualKeyCode:9});
    check("drawer wraps forward Tab",await evaluate("document.activeElement.classList.contains('sidebar-close')"));
    await cdp("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape",code:"Escape",windowsVirtualKeyCode:27});
    await waitFor("!document.querySelector('[role=dialog]')");
    check("Escape returns focus and restores background",await evaluate("document.activeElement.classList.contains('sidebar-trigger') && !document.querySelector('.main-panel').inert"));
    await evaluate("document.querySelector('.sidebar-trigger').click()");
    await clickText("What are my largest expenses?");
    await waitFor("!document.querySelector('[role=dialog]') && document.activeElement.tagName==='TEXTAREA'");
    check("mobile FAQ focuses populated composer",await evaluate("document.querySelector('textarea').value.includes('largest')"));
    await screenshot("mobile-results");
    await evaluate("document.querySelector('.sidebar-trigger').click()");
    await clickText("Expense Analysis");
    await waitFor("!document.querySelector('[role=dialog]') && document.querySelector('table')");
    check("mobile table supports its own horizontal scroll",await evaluate("document.querySelector('.financial-table__scroll').scrollWidth>document.querySelector('.financial-table__scroll').clientWidth"));
    await screenshot("mobile-table");
    check("mobile content has no page overflow",await evaluate("document.documentElement.scrollWidth<=innerWidth"));
    await cdp("Emulation.setEmulatedMedia",{features:[{name:"prefers-reduced-motion",value:"reduce"}]});
    await sendPrompt("no data");
    await sleep(150);
    check("reduced motion reveals promptly without decorative effects",await evaluate("!document.querySelector('.message--forming,.message-birth,.thinking-bubbles') && Boolean(document.querySelector('.processing-status'))"));
    await waitFor("document.body.textContent.includes('No matching financial data')");
    await screenshot("mobile-reduced-motion");
    await evaluate("document.querySelector('.sidebar-trigger').click()");
    await clickText("Ask a Question");
    await waitFor("!document.querySelector('.message') && document.activeElement.tagName==='TEXTAREA'");
    await setInput("   ");
    check("whitespace cannot send",await evaluate("document.querySelector('.send-button').disabled"));
    await setInput("IME composition");
    await evaluate("document.querySelector('textarea').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true}))");
    check("IME Enter does not send",await evaluate("!document.querySelector('.message')"));
    await cdp("Input.dispatchKeyEvent",{type:"keyDown",key:"Enter",code:"Enter",windowsVirtualKeyCode:13,modifiers:8,text:"\r"});
    check("Shift Enter inserts newline",await evaluate("document.querySelector('textarea').value.includes('\\n') && !document.querySelector('.message')"));
    await cdp("Input.dispatchKeyEvent",{type:"keyDown",key:"Enter",code:"Enter",windowsVirtualKeyCode:13,text:"\r"});
    await waitFor("document.querySelector('.message--aqua')");
    check("keyboard Enter sends one message",await evaluate("document.querySelectorAll('.message--user').length===1"));
    await cdp("Emulation.setEmulatedMedia",{features:[{name:"prefers-reduced-motion",value:"no-preference"}]});
    await evaluate("document.querySelectorAll('canvas').forEach(c=>c.getContext('webgl2').getExtension('WEBGL_lose_context').loseContext())");
    await waitFor("document.querySelector('.chat-bar-fallback') && document.querySelector('.logo-fallback')");
    check("both WebGL context losses preserve fallbacks and textarea",await evaluate("document.querySelector('textarea') && !document.querySelectorAll('canvas').length"));
    await screenshot("mobile-webgl-fallback");
    await waitFor("!document.querySelector('.processing-status')");
    await sendPrompt("fallback question");
    await waitFor("document.querySelectorAll('.message--aqua').length===2 && !document.querySelector('.message--forming')");
    check("WebGL fallback remains functional",await evaluate("document.querySelectorAll('.message--user').length===2"));
    console.log(JSON.stringify({ artifactDir, checks, errors, warnings }));
  }
  }
  await writeFile(path.join(artifactDir, failureMode ? `${failureMode}-results.json` : "results.json"), JSON.stringify({ checks, errors, warnings, failureMode }, null, 2));
  if (errors.length && !failureMode) process.exitCode = 1;
} catch (error) {
  console.error(error.stack);
  await writeFile(path.join(artifactDir, failureMode ? `${failureMode}-results.json` : "results.json"), JSON.stringify({ checks, errors, warnings, failure: error.message }, null, 2));
  process.exitCode = 1;
} finally {
  if(socket?.readyState===1) { socket.send(JSON.stringify({id:999999,method:"Browser.close"})); await sleep(200); }
  socket?.close();
  browser.kill();
  clearInterval(keepAlive);
}
