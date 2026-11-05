"""Run CET bridge under real Lua with mocked CET callbacks, in a temporary folder."""
import ctypes, json, os, pathlib, shutil, tempfile
root=pathlib.Path(__file__).resolve().parents[1]
lib=ctypes.CDLL('liblua5.4.so.0')
lib.luaL_newstate.restype=ctypes.c_void_p
lib.luaL_openlibs.argtypes=[ctypes.c_void_p]
lib.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p];lib.luaL_loadstring.restype=ctypes.c_int
lib.lua_pcallk.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_longlong,ctypes.c_void_p];lib.lua_pcallk.restype=ctypes.c_int
lib.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p];lib.lua_tolstring.restype=ctypes.c_char_p
lib.lua_close.argtypes=[ctypes.c_void_p]
code=r'''
local callbacks={};local observers={}
local request=nil
local function encode(v)
 if type(v)=='string' then return string.format('%q',v) end
 if type(v)~='table' then return tostring(v) end
 local rows={}
 for k,value in pairs(v) do rows[#rows+1]=string.format('%q',tostring(k))..':'..encode(value) end
 return '{'..table.concat(rows,',')..'}'
end
json={encode=encode,decode=function(raw)return request end}
function registerForEvent(event, fn) callbacks[event]=fn end
function ObserveAfter(class, method, fn)
 assert(method=='UnlockAchievement','only unlock is observed')
 observers[#observers+1]=fn
end
function EnumInt(v) error('test fallback: unsupported') end
dofile('init.lua')
callbacks.onInit()
assert(#observers==2)
observers[1]({},'gamedataAchievement.TheFool')
observers[1]({},40) -- same enum, duplicate must be harmless to receiver
observers[1]({},999) -- unknown is rejected
observers[1]({},'gamedataAchievement.TheLovers')
observers[1]({},setmetatable({value='TheWorld'},{__tostring=function()return 'gamedataAchievement : TheWorld (48)'end}))
callbacks.onUpdate(6)
-- Exercise diagnostic allowlist and replay/expiry checks without any game mutation.
JournalRequestContext={new=function()return {}end}
JournalRequestStateFilter={new=function()return {}end}
local module=dofile('missions.lua')
local function writeRequest(r)
 request=r;local f=assert(io.open('mission-request.json','w'));f:write('{}');f:close()
end
Game={GetPlayer=function()return {} end,
 GetQuestsSystem=function()return {GetFactStr=function(_,name)
  if name=='mq033_grafitti_counter' then return 8 end
  if name=='sq025_scans_done' then return 4 end
  return 0
 end,SetFactStr=function()error('mutation prohibited')end}end,
 GetJournalManager=function()return {GetTarots=function(_,ctx)
 assert(ctx and ctx.stateFilter,'GetTarots requires one context argument')
 local f=ctx.stateFilter;assert(f.active and f.inactive and f.succeeded and f.failed)
 return {{GetId=function()return 'tarot_test'end,GetIndex=function()return 7 end,GetIsMinorArcana=function()return false end}}
 end,GetEntryState=function()return {value='Active'}end,GetEntryHash=function()return 123 end,
 GetQuests=function(_,ctx)assert(ctx.stateFilter.active);return {}end,
 ChangeEntryState=function()error('journal mutation prohibited')end}end}
writeRequest({version=1,action='set_fact',id='bad',expires=os.time()+30})
module.poll();assert(io.open('missions-report.json','r')==nil)
writeRequest({version=1,action='inspect_missions',id='expired',expires=os.time()-1})
module.poll();assert(io.open('missions-report.json','r')==nil)
writeRequest({version=1,action='inspect_missions',id='good',expires=os.time()+30})
module.poll();local report=assert(io.open('missions-report.json','r'));report:close()
os.remove('missions-report.json');module.poll();assert(io.open('missions-report.json','r')==nil)
writeRequest({version=1,action='inspect_missions',id='final',expires=os.time()+30})
module.poll()
callbacks.onShutdown()
'''
with tempfile.TemporaryDirectory() as d:
 for name in ['init.lua','ids.lua','missions.lua']:shutil.copy(root/'CET-мост'/'local_achievement_bridge'/name,d)
 old=os.getcwd();os.chdir(d)
 state=lib.luaL_newstate();lib.luaL_openlibs(state)
 try:
  rc=lib.luaL_loadstring(state,code.encode()) or lib.lua_pcallk(state,0,0,0,0,None)
  if rc:raise RuntimeError(lib.lua_tolstring(state,-1,None).decode())
  rows=[json.loads(l) for l in pathlib.Path('unlocks.jsonl').read_text().splitlines()]
  assert [r['id'] for r in rows]==['TheFool','TheFool','TheLovers','TheWorld'],rows
  assert all(r['event']=='achievement_unlocked' for r in rows)
  status=json.loads(pathlib.Path('bridge-status.json').read_text())
  assert status['events']==4 and status['observed'] is True
  report=json.loads(pathlib.Path('missions-report.json').read_text())
  assert report['readOnly'] is True and report['facts']['mq033_grafitti_counter']==8
  assert report['facts']['sq025_scans_done']==4
  assert report['bridgeVersion']=='2.1' and 'error' not in report
  assert report['tarots']['1']['id']=='tarot_test' and report['tarots']['1']['state']=='Active'
  print('PASS: GetTarots receives a context with all four states; entry is returned and serialized.')
  print('PASS: diagnostic allowlist, expiry, replay and read-only report validated.')
  print('PASS: real Lua parses bridge; enum name and numeric IDs work; unknown ID rejected; JSONL/status valid.')
  print('NOTE: CET engine hooks mocked; compatibility with actual game is not established.')
 finally:lib.lua_close(state);os.chdir(old)
