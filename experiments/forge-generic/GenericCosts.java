package deckdoctor.generic;

import forge.game.cost.*;
import forge.game.card.*;
import forge.game.player.*;
import forge.game.spellability.*;
import forge.game.zone.ZoneType;
import java.util.*;

/** Decisions by cost shape; Forge performs the actual payment. */
public final class GenericCosts extends StrictCosts {
    private final GenericController controller;
    public GenericCosts(Player p,SpellAbility sa,boolean effect,GenericController controller) {
        super(p,sa,effect);this.controller=controller;
    }
    public PaymentDecision visit(CostPartMana c) {return PaymentDecision.number(0);}
    public PaymentDecision visit(CostTap c) {return c.canPay(ability,player,isEffect())?PaymentDecision.number(1):null;}
    public PaymentDecision visit(CostUntap c) {return c.canPay(ability,player,isEffect())?PaymentDecision.number(1):null;}
    public PaymentDecision visit(CostPayLife c) {return c.canPay(ability,player,isEffect())?PaymentDecision.number(c.getAbilityAmount(ability)):null;}
    public PaymentDecision visit(CostDiscard c) {
        CardCollection hand=new CardCollection(player.getCardsIn(ZoneType.Hand));
        if(c.payCostFromSource()) return hand.contains(source)?PaymentDecision.card(source):null;
        if(c.getType().equals("Random")) throw new UnsupportedOperationException("random discard cost not implemented");
        if(c.getType().equals("Hand")) return PaymentDecision.card(hand);
        CardCollection valid=CardLists.getValidCards(hand,c.getType(),player,source,ability);
        return pick(valid,c.getAbilityAmount(ability),"discard-cost");
    }
    public PaymentDecision visit(CostSacrifice c) {
        CardCollection own=new CardCollection(player.getCardsIn(ZoneType.Battlefield));
        if(c.payCostFromSource()) return c.canPay(ability,player,isEffect())?PaymentDecision.card(source):null;
        CardCollection valid=CardLists.getValidCards(own,c.getType(),player,source,ability);
        valid.removeIf(x->!x.canBeSacrificedBy(ability,false));
        return pick(valid,c.getAbilityAmount(ability),"sacrifice-cost");
    }
    public PaymentDecision visit(CostReveal c) {
        CardCollection valid=CardLists.getValidCards(player.getCardsIn(ZoneType.Hand),c.getType(),player,source,ability);
        return pick(valid,c.getAbilityAmount(ability),"reveal-cost");
    }
    private PaymentDecision pick(CardCollection valid,int count,String kind) {
        if(count<0 || valid.size()<count) return null;
        List<Card> choices=new ArrayList<>(valid);
        choices.sort(Comparator.comparingDouble(controller::discardScore).reversed().thenComparingInt(Card::getId));
        CardCollection selected=new CardCollection(choices.subList(0,count));
        controller.ctx.log(kind,"source",source.getName(),"options",valid.stream().map(Card::getName).toList(),"chosen",selected.stream().map(Card::getName).toList());
        return PaymentDecision.card(selected);
    }
}
