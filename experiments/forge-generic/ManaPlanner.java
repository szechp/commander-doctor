package deckdoctor.generic;

import forge.card.*;
import forge.game.ability.AbilityUtils;
import forge.game.card.Card;
import forge.game.cost.*;
import forge.game.mana.*;
import forge.game.player.*;
import forge.game.spellability.*;
import forge.game.zone.ZoneType;
import java.util.*;

/** Bounded payment search by ability shape, never by card name. */
final class ManaPlanner {
    record Option(SpellAbility ability,byte colour,int amount) {}
    private final GenericController controller;
    private final Player player;
    private final SpellAbility payingFor;
    private final List<List<Option>> sources=new ArrayList<>();
    private final List<String> unknown=new ArrayList<>();
    private int nodes;

    ManaPlanner(GenericController controller,SpellAbility payingFor) {
        this.controller=controller;player=controller.getPlayer();this.payingFor=payingFor;
    }
    boolean pay(ManaCostBeingPaid cost,ManaConversionMatrix matrix) {
        ManaPool pool=player.getManaPool();pool.applyCardMatrix(matrix);
        ManaCostBeingPaid preview=new ManaCostBeingPaid(cost);
        for(Mana m:pool) if(m.meetsManaRestrictions(payingFor) && preview.isNeeded(m,pool)) preview.payMana(m,pool);
        if(!preview.isPaid()) discover();
        List<Option> plan=search(preview,0);
        if(plan==null) {
            if(!unknown.isEmpty()) throw new UnsupportedOperationException("unmodeled mana sources while paying for "+payingFor.getHostCard().getName()+": "+unknown);
            return false;
        }
        pool.payManaCostFromPool(cost,payingFor,false,new ArrayList<>());
        for(Option option:plan) {
            if(cost.isPaid()) break;
            SpellAbility ability=option.ability();
            ability.setManaExpressChoice(ColorSet.fromMask(option.colour()));
            Byte previous=controller.preferredManaColour;controller.preferredManaColour=option.colour();
            try {if(!ability.canPlay() || !PlaySpellAbility.playSpellAbility(controller,player,ability)) throw new UnsupportedOperationException("planned mana activation failed");}
            finally {controller.preferredManaColour=previous;}
            pool.payManaFromAbility(payingFor,cost,ability);
        }
        if(!cost.isPaid()) throw new UnsupportedOperationException("actual mana production differs from planned production");
        return true;
    }
    private void discover() {
        for(Card card:player.getCardsIn(ZoneType.Battlefield)) {
            List<Option> modes=new ArrayList<>();
            for(SpellAbility ability:card.getManaAbilities()) {
                ability.setActivatingPlayer(player);
                if(!ability.canPlay()) continue;
                if((ability.getApi()!=forge.game.ability.ApiType.Mana && ability.getApi()!=forge.game.ability.ApiType.ManaReflected) ||
                   !ability.getPayCosts().getCostParts().stream().allMatch(c->c instanceof CostTap || c instanceof CostPartMana && ((CostPartMana)c).getMana().isZero()) ||
                   ability.getPayCosts().getCostPartByType(CostTap.class)==null) {
                    unknown.add(card.getName()+" ["+ability.getApi()+", "+ability.getPayCosts().toSimpleString()+"]");continue;
                }
                int amount=AbilityUtils.calculateAmount(card,ability.getParamOrDefault("Amount","1"),ability);
                if(amount<1 || amount>20) {unknown.add(card.getName()+" amount="+amount);continue;}
                for(String symbol:List.of("W","U","B","R","G","C")) {
                    boolean produces=ability.getApi()==forge.game.ability.ApiType.ManaReflected
                        ? forge.game.card.CardUtil.getReflectableManaColors(ability).stream().anyMatch(c->MagicColor.toShortString(c).equals(symbol))
                        : ability.getManaPart().canProduce(symbol,ability);
                    if(!produces) continue;
                    byte colour=MagicColor.fromName(symbol);
                    Mana sample=new Mana(colour,card,ability.getManaPart(),player);
                    if(sample.meetsManaRestrictions(payingFor) && payingFor.allowsPayingWithShard(card,colour)) modes.add(new Option(ability,colour,amount));
                }
            }
            if(!modes.isEmpty()) sources.add(modes);
        }
    }
    private List<Option> search(ManaCostBeingPaid remaining,int index) {
        if(remaining.isPaid()) return new ArrayList<>();
        if(++nodes>4096) throw new UnsupportedOperationException("mana search budget exhausted");
        if(index==sources.size()) return null;
        for(Option option:sources.get(index)) {
            ManaCostBeingPaid next=new ManaCostBeingPaid(remaining);
            Mana token=new Mana(option.colour(),option.ability().getHostCard(),option.ability().getManaPart(),player);
            boolean used=false;
            for(int i=0;i<option.amount() && next.isNeeded(token,player.getManaPool());i++) {next.payMana(token,player.getManaPool());used=true;}
            if(!used) continue;
            List<Option> tail=search(next,index+1);
            if(tail!=null) {tail.add(0,option);return tail;}
        }
        return search(remaining,index+1);
    }
}
