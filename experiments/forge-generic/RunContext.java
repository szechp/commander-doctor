package deckdoctor.generic;

import forge.game.Game;
import java.util.*;

/** Per-run audit data. Policy never receives a library order or a future draw. */
public final class RunContext {
    public final long seed;
    public final Map<String,Integer> requirements;
    public final List<Map<String,Object>> trace=new ArrayList<>();
    public final Map<String,Integer> events=new TreeMap<>();
    public final Set<String> limitations=new TreeSet<>();
    public final List<Map<String,Object>> snapshotChecks=new ArrayList<>();
    public final boolean inspectCopies;
    public int turn, actions, opportunities, firstSuccess, normalDraws, effectDraws;
    public boolean finished;
    public int branchDecision=-1, branchIndex, decisions;
    public String error;
    public String failureStatus="error";

    public RunContext(long seed, Map<String,Integer> requirements, boolean inspectCopies) {
        this.seed=seed;this.requirements=requirements;this.inspectCopies=inspectCopies;
        limitations.add("Heuristic policy; not an optimal-play or impossibility proof");
        limitations.add("No combat or opponent interaction; action discovery is limited to own visible zones");
        limitations.add("Optional costs/splice declined; mana planner supports unconditional zero-input tap sources only");
    }
    public void log(String kind,Object... pairs) {
        Map<String,Object> row=new LinkedHashMap<>();row.put("kind",kind);row.put("turn",turn);
        for(int i=0;i<pairs.length;i+=2) row.put((String)pairs[i],pairs[i+1]);
        trace.add(row);
    }
    public void event(String kind) {
        events.merge(kind,1,Integer::sum);
        if(firstSuccess==0 && turn>0 && !requirements.isEmpty() && requirements.entrySet().stream().allMatch(e->events.getOrDefault(e.getKey(),0)>=e.getValue())) firstSuccess=turn;
    }
    public Map<String,Object> result(Game game,String deck,long elapsed) {
        Map<String,Object> out=new LinkedHashMap<>();
        out.put("deck",deck);out.put("seed",seed);out.put("status",error!=null?failureStatus:finished?"completed_under_policy":"ended_before_cap");
        out.put("error",error);out.put("normal_draws",normalDraws);out.put("effect_draws",effectDraws);
        out.put("requirements",requirements);out.put("first_observed_success_turn",firstSuccess==0?null:firstSuccess);
        out.put("events",events);out.put("actions_enumerated",opportunities);out.put("actions_attempted",actions);
        out.put("limitations",limitations);out.put("snapshot_checks",snapshotChecks);
        out.put("elapsed_ms",elapsed/1e6);out.put("trace",trace);
        out.put("final_state",game==null?null:SnapshotAudit.state(game));
        return out;
    }
}
