package deckdoctor.generic;
import forge.game.cost.*; import forge.game.player.*; import forge.game.spellability.*;
public abstract class StrictCosts extends CostDecisionMakerBase {
public StrictCosts(Player p, SpellAbility s, boolean effect) {super(p,effect,s,s.getHostCard());}
public boolean paysRightAfterDecision() {return true;}
public PaymentDecision visit(CostBehold cost) {throw new UnsupportedOperationException("cost:CostBehold");}
public PaymentDecision visit(CostBeholdExile cost) {throw new UnsupportedOperationException("cost:CostBeholdExile");}
public PaymentDecision visit(CostGainControl cost) {throw new UnsupportedOperationException("cost:CostGainControl");}
public PaymentDecision visit(CostChooseColor cost) {throw new UnsupportedOperationException("cost:CostChooseColor");}
public PaymentDecision visit(CostChooseCreatureType cost) {throw new UnsupportedOperationException("cost:CostChooseCreatureType");}
public PaymentDecision visit(CostCollectEvidence cost) {throw new UnsupportedOperationException("cost:CostCollectEvidence");}
public PaymentDecision visit(CostDiscard cost) {throw new UnsupportedOperationException("cost:CostDiscard");}
public PaymentDecision visit(CostDamage cost) {throw new UnsupportedOperationException("cost:CostDamage");}
public PaymentDecision visit(CostDraw cost) {throw new UnsupportedOperationException("cost:CostDraw");}
public PaymentDecision visit(CostExile cost) {throw new UnsupportedOperationException("cost:CostExile");}
public PaymentDecision visit(CostExileFromStack cost) {throw new UnsupportedOperationException("cost:CostExileFromStack");}
public PaymentDecision visit(CostExiledMoveToGrave cost) {throw new UnsupportedOperationException("cost:CostExiledMoveToGrave");}
public PaymentDecision visit(CostExert cost) {throw new UnsupportedOperationException("cost:CostExert");}
public PaymentDecision visit(CostEnlist cost) {throw new UnsupportedOperationException("cost:CostEnlist");}
public PaymentDecision visit(CostFlipCoin cost) {throw new UnsupportedOperationException("cost:CostFlipCoin");}
public PaymentDecision visit(CostForage cost) {throw new UnsupportedOperationException("cost:CostForage");}
public PaymentDecision visit(CostRollDice cost) {throw new UnsupportedOperationException("cost:CostRollDice");}
public PaymentDecision visit(CostMill cost) {throw new UnsupportedOperationException("cost:CostMill");}
public PaymentDecision visit(CostAddMana cost) {throw new UnsupportedOperationException("cost:CostAddMana");}
public PaymentDecision visit(CostPayLife cost) {throw new UnsupportedOperationException("cost:CostPayLife");}
public PaymentDecision visit(CostPayEnergy cost) {throw new UnsupportedOperationException("cost:CostPayEnergy");}
public PaymentDecision visit(CostGainLife cost) {throw new UnsupportedOperationException("cost:CostGainLife");}
public PaymentDecision visit(CostPartMana cost) {throw new UnsupportedOperationException("cost:CostPartMana");}
public PaymentDecision visit(CostPromiseGift cost) {throw new UnsupportedOperationException("cost:CostPromiseGift");}
public PaymentDecision visit(CostPutCardToLib cost) {throw new UnsupportedOperationException("cost:CostPutCardToLib");}
public PaymentDecision visit(CostTap cost) {throw new UnsupportedOperationException("cost:CostTap");}
public PaymentDecision visit(CostSacrifice cost) {throw new UnsupportedOperationException("cost:CostSacrifice");}
public PaymentDecision visit(CostReturn cost) {throw new UnsupportedOperationException("cost:CostReturn");}
public PaymentDecision visit(CostReveal cost) {throw new UnsupportedOperationException("cost:CostReveal");}
public PaymentDecision visit(CostRevealChosen cost) {throw new UnsupportedOperationException("cost:CostRevealChosen");}
public PaymentDecision visit(CostRemoveAnyCounter cost) {throw new UnsupportedOperationException("cost:CostRemoveAnyCounter");}
public PaymentDecision visit(CostRemoveCounter cost) {throw new UnsupportedOperationException("cost:CostRemoveCounter");}
public PaymentDecision visit(CostPutCounter cost) {throw new UnsupportedOperationException("cost:CostPutCounter");}
public PaymentDecision visit(CostPutCounterYou cost) {throw new UnsupportedOperationException("cost:CostPutCounterYou");}
public PaymentDecision visit(CostUntapType cost) {throw new UnsupportedOperationException("cost:CostUntapType");}
public PaymentDecision visit(CostUntap cost) {throw new UnsupportedOperationException("cost:CostUntap");}
public PaymentDecision visit(CostUnattach cost) {throw new UnsupportedOperationException("cost:CostUnattach");}
public PaymentDecision visit(CostTapType cost) {throw new UnsupportedOperationException("cost:CostTapType");}
public PaymentDecision visit(CostPayShards cost) {throw new UnsupportedOperationException("cost:CostPayShards");}
public PaymentDecision visit(CostBlight cost) {throw new UnsupportedOperationException("cost:CostBlight");}
}
