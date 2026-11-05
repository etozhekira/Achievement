-- Read-only mission inspection. This module NEVER modifies game/quest state.
local lastRequest=nil
local facts={'mq033_current_count','mq033_grafitti_counter','mq033_done',
 'mq033_ep1_done','sq025_active','sq025_scans_done','sq025_done','sq025_delamain_done',
 'sq025_angry_done','sq025_mean_done','sq025_sad_done','sq025_suicidal_done',
 'sq025_deep_done','sq025_manic_done','sq025_scared_done','ow_psychos_done',
 'ow_psychos_killed','ow_psychos_reward_collected'}

local function context()
 -- Struct-valued fields are copied: assign the complete filter back to context.
 local ctx=JournalRequestContext.new()
 local filter=JournalRequestStateFilter.new()
 filter.inactive=true;filter.active=true;filter.succeeded=true;filter.failed=true
 ctx.stateFilter=filter
 return ctx
end
local function enumName(value)
 local ok,name=pcall(function()return value.value end)
 if ok and type(name)=='string' then return name end
 return tostring(value)
end
local function process()
 local f=io.open('mission-request.json','r');if not f then return end
 local raw=f:read(4097);f:close();if #raw>4096 then return end
 local ok,r=pcall(json.decode,raw);if not ok or type(r)~='table' then return end
 if r.version~=1 or r.action~='inspect_missions' or type(r.id)~='string' or #r.id>64 then return end
 if r.id==lastRequest then return end
 if type(r.expires)~='number' or r.expires<os.time() or r.expires>os.time()+120 then return end
 if not Game or not Game.GetPlayer() then return end
 lastRequest=r.id
 local report={version=2,bridgeVersion='2.1',requestId=r.id,readOnly=true,
   updated=os.time(),facts={},tarots={},quests={},errors={}}
 local function step(name,fn)
  local success,err=pcall(fn)
  if not success then report.errors[#report.errors+1]=name..': '..tostring(err) end
 end
 step('facts',function()
  local qs=Game.GetQuestsSystem()
  for _,name in ipairs(facts) do report.facts[name]=tonumber(qs:GetFactStr(name)) end
 end)
 local jm
 step('journal',function()jm=assert(Game.GetJournalManager(),'JournalManager недоступен')end)
 if jm then
  step('tarots',function()
   local entries=jm:GetTarots(context())
   assert(type(entries)=='table','GetTarots не вернул массив')
   assert(#entries<=256,'Неожиданно большой список таро')
   for _,entry in ipairs(entries) do
    step('tarot entry',function()
     local row={id=tostring(entry:GetId()),index=tonumber(entry:GetIndex()),
       minor=entry:GetIsMinorArcana(),state=enumName(jm:GetEntryState(entry)),
       hash=tostring(jm:GetEntryHash(entry))}
     report.tarots[#report.tarots+1]=row
    end)
   end
  end)
  -- Inspect only the requested mission families, not the entire player's journal.
  step('quests',function()
   local ctx=context()
   local roots=jm:GetQuests(ctx)
   assert(type(roots)=='table','GetQuests не вернул массив')
   local visited={};local limit=0
   local function walk(entry,path,depth)
    if depth>8 or limit>=512 then return end
    local id=tostring(entry:GetId());local hash=tostring(jm:GetEntryHash(entry))
    if visited[hash] then return end
    visited[hash]=true;limit=limit+1
    local row={id=id,hash=hash,path=path..'/'..id,state=enumName(jm:GetEntryState(entry)),children={}}
    -- Some entry types are objectives; unsupported counter queries are optional.
    local a,current=pcall(function()return jm:GetObjectiveCurrentCounter(entry)end)
    local b,total=pcall(function()return jm:GetObjectiveTotalCounter(entry)end)
    if a and b and tonumber(total) and tonumber(total)>0 then
     row.current=tonumber(current);row.total=tonumber(total)
    end
    local got,children=pcall(function()return jm:GetChildren(entry,ctx)end)
    if got and type(children)=='table' then
     for _,child in ipairs(children) do
      local success,node=pcall(walk,child,row.path,depth+1)
      if success and node then row.children[#row.children+1]=node end
     end
    elseif not got then row.childrenError=tostring(children) end
    return row
   end
   for _,quest in ipairs(roots) do
    local id=tostring(quest:GetId()):lower()
    if id:find('mq033',1,true) or id:find('sq025',1,true) or id:find('psycho',1,true) then
     step('quest '..id,function()
      local row=walk(quest,'',0);if row then report.quests[#report.quests+1]=row end
     end)
    end
   end
  end)
 end
 if #report.errors>0 then report.error=table.concat(report.errors,'; ') end
 local out=io.open('missions-report.json','w')
 if out then out:write(json.encode(report));out:close() end
end
return {poll=process}
