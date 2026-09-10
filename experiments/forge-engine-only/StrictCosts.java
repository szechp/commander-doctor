package deckdoctor.spike;
import forge.game.cost.*; import forge.game.player.*; import forge.game.spellability.*;
public class StrictCosts extends CostDecisionMakerBase {
public StrictCosts(Player p, SpellAbility s, boolean effect) {super(p,effect,s,s.getHostCard());}
public boolean paysRightAfterDecision() {return true;}
public PaymentDecision visit(CostBehold cost) {throw new UnsupportedOperationException("CostBehold");}
public PaymentDecision visit(CostBeholdExile cost) {throw new UnsupportedOperationException("CostBeholdExile");}
public PaymentDecision visit(CostGainControl cost) {throw new UnsupportedOperationException("CostGainControl");}
public PaymentDecision visit(CostChooseColor cost) {throw new UnsupportedOperationException("CostChooseColor");}
public PaymentDecision visit(CostChooseCreatureType cost) {throw new UnsupportedOperationException("CostChooseCreatureType");}
public PaymentDecision visit(CostCollectEvidence cost) {throw new UnsupportedOperationException("CostCollectEvidence");}
public PaymentDecision visit(CostDiscard cost) {
    if(!cost.getType().equals("Card") || cost.getAbilityAmount(ability)!=1)
        throw new UnsupportedOperationException("unsupported discard cost "+cost);
    for(forge.game.card.Card c:player.getCardsIn(forge.game.zone.ZoneType.Hand))
        if(c.getName().equals("Kitchen Imp")) {
            System.out.println("DISCARD_COST "+c.getName());
            return PaymentDecision.card(c);
        }
    return null;
}
public PaymentDecision visit(CostDamage cost) {throw new UnsupportedOperationException("CostDamage");}
public PaymentDecision visit(CostDraw cost) {throw new UnsupportedOperationException("CostDraw");}
public PaymentDecision visit(CostExile cost) {throw new UnsupportedOperationException("CostExile");}
public PaymentDecision visit(CostExileFromStack cost) {throw new UnsupportedOperationException("CostExileFromStack");}
public PaymentDecision visit(CostExiledMoveToGrave cost) {throw new UnsupportedOperationException("CostExiledMoveToGrave");}
public PaymentDecision visit(CostExert cost) {throw new UnsupportedOperationException("CostExert");}
public PaymentDecision visit(CostEnlist cost) {throw new UnsupportedOperationException("CostEnlist");}
public PaymentDecision visit(CostFlipCoin cost) {throw new UnsupportedOperationException("CostFlipCoin");}
public PaymentDecision visit(CostForage cost) {throw new UnsupportedOperationException("CostForage");}
public PaymentDecision visit(CostRollDice cost) {throw new UnsupportedOperationException("CostRollDice");}
public PaymentDecision visit(CostMill cost) {throw new UnsupportedOperationException("CostMill");}
public PaymentDecision visit(CostAddMana cost) {throw new UnsupportedOperationException("CostAddMana");}
public PaymentDecision visit(CostPayLife cost) {throw new UnsupportedOperationException("CostPayLife");}
public PaymentDecision visit(CostPayEnergy cost) {throw new UnsupportedOperationException("CostPayEnergy");}
public PaymentDecision visit(CostGainLife cost) {throw new UnsupportedOperationException("CostGainLife");}
public PaymentDecision visit(CostPartMana cost) {return PaymentDecision.number(0);}
public PaymentDecision visit(CostPromiseGift cost) {throw new UnsupportedOperationException("CostPromiseGift");}
public PaymentDecision visit(CostPutCardToLib cost) {throw new UnsupportedOperationException("CostPutCardToLib");}
public PaymentDecision visit(CostTap cost) {return cost.canPay(ability, player, isEffect()) ? PaymentDecision.number(1) : null;}
public PaymentDecision visit(CostSacrifice cost) {throw new UnsupportedOperationException("CostSacrifice");}
public PaymentDecision visit(CostReturn cost) {throw new UnsupportedOperationException("CostReturn");}
public PaymentDecision visit(CostReveal cost) {throw new UnsupportedOperationException("CostReveal");}
public PaymentDecision visit(CostRevealChosen cost) {throw new UnsupportedOperationException("CostRevealChosen");}
public PaymentDecision visit(CostRemoveAnyCounter cost) {throw new UnsupportedOperationException("CostRemoveAnyCounter");}
public PaymentDecision visit(CostRemoveCounter cost) {throw new UnsupportedOperationException("CostRemoveCounter");}
public PaymentDecision visit(CostPutCounter cost) {throw new UnsupportedOperationException("CostPutCounter");}
public PaymentDecision visit(CostPutCounterYou cost) {throw new UnsupportedOperationException("CostPutCounterYou");}
public PaymentDecision visit(CostUntapType cost) {throw new UnsupportedOperationException("CostUntapType");}
public PaymentDecision visit(CostUntap cost) {throw new UnsupportedOperationException("CostUntap");}
public PaymentDecision visit(CostUnattach cost) {throw new UnsupportedOperationException("CostUnattach");}
public PaymentDecision visit(CostTapType cost) {throw new UnsupportedOperationException("CostTapType");}
public PaymentDecision visit(CostPayShards cost) {throw new UnsupportedOperationException("CostPayShards");}
public PaymentDecision visit(CostBlight cost) {throw new UnsupportedOperationException("CostBlight");}
}
