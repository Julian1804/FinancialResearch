const CODE_ALIAS_PRIORITY=["public_fund_code","fund_security_code","listing_code","public_fund_id"];

function csvCell(value){
  return `"${String(value??"").replaceAll('"','""')}"`;
}

function safeFilenamePart(value,fallback="unknown"){
  const cleaned=String(value??"").trim().replace(/[^A-Za-z0-9._-]+/g,"-").replace(/^-+|-+$/g,"");
  return cleaned||fallback;
}

export function fundExternalCode(detail){
  const aliases=Array.isArray(detail?.aliases)?detail.aliases:[];
  for(const aliasType of CODE_ALIAS_PRIORITY){
    const match=aliases.find(alias=>alias?.alias_type===aliasType&&String(alias?.alias_value||"").trim());
    if(match)return {type:match.alias_type,value:String(match.alias_value)};
  }
  const codeAlias=aliases.find(alias=>String(alias?.alias_type||"").includes("code")&&String(alias?.alias_value||"").trim());
  return codeAlias?{type:String(codeAlias.alias_type),value:String(codeAlias.alias_value)}:{type:"",value:""};
}

export function buildFundSeriesExport(payload,detail,binding){
  if(!payload?.points?.length)throw new Error("Fund export requires returned points");
  const subject=payload.subject||detail?.subject||{};
  const seriesId=payload.series?.series_id||"";
  if(!subject.subject_type||!subject.subject_id||!payload.metric_id||!seriesId){
    throw new Error("Fund export context is incomplete");
  }
  const external=fundExternalCode(detail);
  const snapshot=payload.snapshot||{};
  const header=[
    "subject_type","subject_id","canonical_name","external_code_type","external_code",
    "metric_id","series_id","requested_start","requested_end","data_state","economic_time","value","unit","currency","scale","time_role",
    "release_id","release_hash","snapshot_id","snapshot_manifest_sha256","binding_id","access_mode",
    "source_family","source_observation_id","source_mapping_basis","provenance_refs",
  ];
  const context=[
    subject.subject_type,subject.subject_id,subject.canonical_name||"",external.type,external.value,
    payload.metric_id,seriesId,payload.requested_interval?.start||"",payload.requested_interval?.end||"",payload.data_state||"",
  ];
  const publication=[
    snapshot.release_id||binding?.release_id||"",
    snapshot.release_hash||binding?.release_hash||"",
    snapshot.snapshot_id||binding?.snapshot_id||"",
    snapshot.manifest_sha256||binding?.manifest_sha256||"",
    snapshot.binding_id||binding?.binding_id||"",
    binding?.access_mode||"",
  ];
  const lines=[header.map(csvCell).join(","),...payload.points.map(row=>[
    ...context,row.economic_time,row.value,row.unit||"",row.currency||"",row.scale??"",row.time_role||"",
    ...publication,row.source?.source_family||"",row.source?.source_observation_id||"",
    row.source?.mapping_basis||"",JSON.stringify(row.source?.provenance_refs||[]),
  ].map(csvCell).join(","))];
  const idSuffix=safeFilenamePart(subject.subject_id).slice(-16);
  const identityPart=external.value?safeFilenamePart(external.value):idSuffix;
  const interval=payload.requested_interval||{};
  return {
    filename:[
      "fr-fund",safeFilenamePart(subject.subject_type),identityPart,idSuffix,
      safeFilenamePart(payload.metric_id),safeFilenamePart(interval.start,"full"),safeFilenamePart(interval.end,"full"),
    ].join("-")+".csv",
    csv:`\ufeff${lines.join("\r\n")}\r\n`,
    rowCount:payload.points.length,
  };
}
