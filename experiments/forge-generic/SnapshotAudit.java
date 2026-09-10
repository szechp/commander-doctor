package deckdoctor.generic;

import forge.game.*;
import forge.game.card.Card;
import forge.game.mana.Mana;
import forge.game.player.Player;
import forge.game.zone.ZoneType;
import forge.util.MyRandom;
import java.io.*;
import java.util.*;

/** Verification only: hidden-zone fingerprints are never used for policy scoring. */
public final class SnapshotAudit {
    public static Map<String,Object> state(Game game) {
        Map<String,Object> state=new LinkedHashMap<>();
        state.put("age",String.valueOf(game.getAge()));state.put("turn",game.getPhaseHandler().getTurn());
        state.put("phase",String.valueOf(game.getPhaseHandler().getPhase()));
        state.put("active_player",game.getPhaseHandler().getPlayerTurn()==null?null:game.getPhaseHandler().getPlayerTurn().getId());
        state.put("priority_player",game.getPhaseHandler().getPriorityPlayer()==null?null:game.getPhaseHandler().getPriorityPlayer().getId());
        List<Object> players=new ArrayList<>();
        for(Player p:game.getPlayers()) {
            Map<String,Object> row=new LinkedHashMap<>();
            row.put("id",p.getId());row.put("life",p.getLife());row.put("lands_played",p.getLandsPlayedThisTurn());
            row.put("spells_cast",p.getSpellsCastThisTurn());row.put("drawn_this_turn",p.getNumDrawnThisTurn());
            row.put("commanders",p.getCommanders().stream().map(Card::getId).toList());
            List<String> mana=new ArrayList<>();for(Mana m:p.getManaPool())mana.add(m.toString()+":"+m.getSourceCard().getId());row.put("mana",mana);
            for(ZoneType zone:List.of(ZoneType.Library,ZoneType.Hand,ZoneType.Command,ZoneType.Battlefield,ZoneType.Graveyard,ZoneType.Exile)) {
                List<Object> cards=new ArrayList<>();
                for(Card c:p.getCardsIn(zone)) cards.add(List.of(c.getId(),c.getName(),c.isTapped(),c.isSick(),c.getCounters().toString(),c.getCurrentStateName().toString()));
                row.put(zone.toString(),cards);
            }
            players.add(row);
        }
        state.put("players",players);
        List<String> stack=new ArrayList<>();for(var entry:game.getStack()) {var sa=entry.getSpellAbility();stack.add(sa.getHostCard().getId()+":"+sa.isSpell()+":"+sa.isTrigger()+":"+sa.getApi());}
        state.put("stack",stack);return state;
    }
    private static Random cloneRandom(Random random) throws Exception {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        try(ObjectOutputStream out=new ObjectOutputStream(bytes)) {out.writeObject(random);}
        try(ObjectInputStream in=new ObjectInputStream(new ByteArrayInputStream(bytes.toByteArray()))) {return (Random)in.readObject();}
    }
    public static void inspect(Game original,RunContext ctx) {
        Map<String,Object> report=new LinkedHashMap<>();report.put("boundary",original.getStack().isEmpty()?"empty-stack":"nonempty-stack");
        Map<String,Object> before=state(original);
        Random saved=null;
        try {
            saved=cloneRandom(MyRandom.getRandom());
            if(original.getStack().isEmpty()) {
                Player active=original.getPlayers().get(0);
                GenericController policy=(GenericController)active.getController();
                List<String> optionsBefore=policy.discover().stream().map(a->a.key()+":"+a.score()).toList();
                List<Card> order=new ArrayList<>(active.getCardsIn(ZoneType.Library));
                List<Card> reversed=new ArrayList<>(order);Collections.reverse(reversed);
                try {
                    active.getZone(ZoneType.Library).setCards(reversed);
                    List<String> optionsAfter=policy.discover().stream().map(a->a.key()+":"+a.score()).toList();
                    report.put("future_order_does_not_change_action_options_or_scores",optionsBefore.equals(optionsAfter));
                } finally {active.getZone(ZoneType.Library).setCards(order);}
            }
            GameSnapshot snapshot=new GameSnapshot(original);
            Game copy=snapshot.makeCopy();
            Map<String,Object> copied=state(copy);
            report.put("state_equal",before.equals(copied));
            report.put("original_stack_size",original.getStack().size());report.put("copied_stack_size",copy.getStack().size());
            List<String> mismatches=new ArrayList<>();
            compare("",before,copied,mismatches);report.put("mismatches",mismatches);
            int originalLife=original.getPlayers().get(0).getLife();
            copy.getPlayers().get(0).setLife(originalLife-3,null);
            report.put("life_mutation_isolated",original.getPlayers().get(0).getLife()==originalLife);
            Card copiedCard=copy.getPlayers().get(0).getCardsIn(ZoneType.Battlefield).stream().findFirst().orElse(null);
            if(copiedCard!=null) {
                Card originalCard=original.findById(copiedCard.getId());boolean tapped=originalCard.isTapped();
                copiedCard.setTapped(!tapped);
                report.put("card_mutation_isolated",originalCard.isTapped()==tapped);
            }
            report.put("original_unchanged",before.equals(state(original)));
            report.put("controllers_are_custom",copy.getPlayers().stream().allMatch(p->p.getController() instanceof GenericController && !p.getController().isAI()));
        } catch(Exception e) {report.put("error",e.toString());}
        finally {if(saved!=null)MyRandom.setRandom(saved);}
        ctx.snapshotChecks.add(report);
        if(!before.equals(state(original))) throw new UnsupportedOperationException("snapshot inspection mutated original state");
    }
    @SuppressWarnings("unchecked")
    private static void compare(String path,Object a,Object b,List<String> differences) {
        if(Objects.equals(a,b))return;
        if(a instanceof Map<?,?> ma && b instanceof Map<?,?> mb) {
            for(Object k:ma.keySet())compare(path+"/"+k,ma.get(k),mb.get(k),differences);
        } else if(a instanceof List<?> la && b instanceof List<?> lb && la.size()==lb.size()) {
            for(int i=0;i<la.size();i++)compare(path+"/"+i,la.get(i),lb.get(i),differences);
        } else differences.add(path+": "+a+" != "+b);
    }
}
