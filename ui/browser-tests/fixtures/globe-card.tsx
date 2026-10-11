import React from "react";
import {createRoot} from "react-dom/client";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {JobCards} from "../../components/job-cards";
import {GlobeJobSchema} from "../../lib/globe-contract";
const row=(n:number)=>({id:`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`,title:`Engineer ${n}`,company:`Synthetic ${n}`,source:"fixture",location:null,remote:null,seniority:null,stack:[],url:`https://example.test/${n}`,apply_url:null,posted_at:null,first_seen_at:"2026-10-07T01:00:00Z",last_seen_at:"2026-10-07T01:00:00Z",status:"new" as const,status_reason:null,score:90,recommendation:"apply" as const,alive:true,experience:null,fit_line:null,salary:null,description_available:false,seniority_origin:"unknown" as const,extraction_state:"not-extracted" as const});
const rows=[row(1),row(2)];
const marker=GlobeJobSchema.parse(rows[1]);
let reads=0;
window.fetch=async()=>{reads++;return Response.json({jobs:[rows[1]]})};
Object.assign(window,{fixtureReads:()=>reads});
const client=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}});
function Fixture(){const [selected,setSelected]=React.useState(rows[0].id);return <QueryClientProvider client={client}><JobCards groups={[{job:rows[0],alternates:[]},{job:marker,alternates:[]}]} globeOpen visiblePostingIds={rows.map(row=>row.id)} selectedId={selected} openerRef={{current:null}} selectJob={id=>setSelected(id!)} /></QueryClientProvider>}
createRoot(document.getElementById("app")!).render(<Fixture/>);
