package deckdoctor.generic;

import forge.*;
import forge.card.*;
import forge.card.mana.ManaCost;
import forge.deck.*;
import forge.game.*;
import forge.game.ability.*;
import forge.game.card.*;
import forge.game.combat.Combat;
import forge.game.cost.*;
import forge.game.keyword.Keyword;
import forge.game.mana.*;
import forge.game.player.*;
import forge.game.replacement.ReplacementEffect;
import forge.game.spellability.*;
import forge.game.trigger.WrappedAbility;
import forge.game.zone.*;
import forge.item.PaperCard;
import forge.util.*;
import forge.util.collect.FCollectionView;
import org.apache.commons.lang3.tuple.ImmutablePair;
import java.util.*;

/** Shared visible-information heuristic policy; no card-specific branches. */
public final class GenericController extends StrictController {
    final RunContext ctx;
    final boolean active;
    private int mulligans, activatedTurn, priorityCalls;
    private final Set<String> failed=new HashSet<>();
    private final Map<String,Integer> activations=new HashMap<>();
    private boolean inspected;
    Byte preferredManaColour;

    @Override protected UnsupportedOperationException unsupported(String decision) {
        // Forge catches some callback exceptions internally. Preserve the failure anyway.
        ctx.error="Unsupported controller decision: "+decision;
        ctx.failureStatus="unsupported";
        return super.unsupported(decision);
    }

    @Override public CounterType chooseCounterType(List<CounterType> options, SpellAbility sa, String prompt, Map<String,Object> params) {
        if(options.isEmpty()) throw unsupported("counter type with no options");
        if(options.size()>1) ctx.limitations.add("Multiple counter types: first engine-provided option chosen");
        ctx.log("counter-type", "options", options.toString(), "chosen", options.get(0).toString());
        return options.get(0);
    }

    public GenericController(Game game,Player player,LobbyPlayer seat,RunContext ctx,boolean active) {
        super(game,player,seat);this.ctx=ctx;this.active=active;
    }
    static String key(SpellAbility sa,int index) {
        return sa.getHostCard().getId()+":"+sa.getHostCard().getZone().getZoneType()+":"+index+":"+sa.getApi()+":"+sa.getPayCosts().toSimpleString();
    }
    record Action(String key,SpellAbility ability,double score) {}
    List<Action> discover() {
        List<Action> actions=new ArrayList<>();
        for(ZoneType zone:List.of(ZoneType.Hand,ZoneType.Command,ZoneType.Battlefield,ZoneType.Graveyard,ZoneType.Exile)) {
            for(Card card:player.getCardsIn(zone)) {
                if(card.isFaceDown()) {ctx.limitations.add("Face-down cards not enumerated");continue;}
                List<SpellAbility> options=card.getAllPossibleAbilities(player,true);
                for(int i=0;i<options.size();i++) {
                    SpellAbility sa=options.get(i);sa.setActivatingPlayer(player);
                    if(sa.isManaAbility() || sa.isTrigger() || !sa.canPlay()) continue;
                    actions.add(new Action(key(sa,i),sa,score(sa)));
                }
            }
        }
        actions.sort(Comparator.comparingDouble(Action::score).reversed().thenComparing(Action::key));
        return actions;
    }
    private double score(SpellAbility sa) {
        Card c=sa.getHostCard();
        double mana=sa.getPayCosts()==null || sa.getPayCosts().getCostMana()==null?0:sa.getPayCosts().getCostMana().getManaCostFor(sa).getCMC();
        if(sa.isLandAbility()) return 100;
        if(c.isCommander() && sa.isSpell()) return 85-mana;
        if(sa.isSpell() && c.hasKeyword(Keyword.MADNESS) && player.getCardsIn(ZoneType.Battlefield).stream().anyMatch(b->b.getSpellAbilities().stream().anyMatch(a->a.getPayCosts()!=null && a.getPayCosts().getCostPartByType(CostDiscard.class)!=null))) return -1;
        double value=sa.isSpell()?35:15;
        if(sa.isSpell() && !c.getManaAbilities().isEmpty()) value+=35;
        if(sa.getApi()==ApiType.Draw) value+=35;
        if(sa.getApi()==ApiType.ChangeZone || sa.getApi()==ApiType.Token) value+=15;
        return value-mana;
    }
    public List<SpellAbility> chooseSpellAbilityToPlay() {
        if(!active || getGame().getPhaseHandler().getPlayerTurn()!=player || !getGame().getPhaseHandler().getPhase().isMain() || !getGame().getStack().isEmpty()) return null;
        if(++priorityCalls>1000) throw new UnsupportedOperationException("priority decision budget exhausted");
        if(activatedTurn!=ctx.turn) {activations.clear();failed.clear();activatedTurn=ctx.turn;}
        List<Action> choices=discover();ctx.opportunities+=choices.size();
        ctx.log("action-options","scope","own-visible-zones/main-phase; timing legal, payment unverified","options",choices.stream().map(a->a.key()+" "+a.ability().getHostCard().getName()).toList());
        if(ctx.inspectCopies && !inspected && ctx.turn>=2) {inspected=true;SnapshotAudit.inspect(getGame(),ctx);}
        List<Action> eligible=new ArrayList<>();
        for(Action a:choices) {
            if(a.score()<0 || failed.contains(a.key())) continue;
            if(a.ability().isActivatedAbility() && activations.getOrDefault(a.key(),0)>=2) {ctx.limitations.add("Activated abilities capped at two uses per turn by policy");continue;}
            eligible.add(a);
        }
        if(eligible.isEmpty())return null;
        int index=0;
        if(++ctx.decisions==ctx.branchDecision) {
            if(ctx.branchIndex<0 || ctx.branchIndex>=eligible.size())throw new UnsupportedOperationException("replay branch index outside available actions");
            index=ctx.branchIndex;ctx.log("replay-branch","decision",ctx.decisions,"index",index,"selected",eligible.get(index).key());
        }
        Action selected=eligible.get(index);failed.add(selected.key());return List.of(selected.ability());
    }
    public boolean playChosenSpellAbility(SpellAbility sa) {
        if(++ctx.actions>200) throw new UnsupportedOperationException("action budget exhausted");
        String origin=sa.getHostCard().getZone().getZoneType().toString();
        List<Action> before=discover();
        String chosen=before.stream().filter(a->a.ability()==sa).map(Action::key).findFirst().orElse(sa.getHostCard().getId()+":"+sa.getApi());
        ctx.log("action-selected","card",sa.getHostCard().getName(),"api",String.valueOf(sa.getApi()),"cost",sa.getPayCosts().toSimpleString());
        boolean played=PlaySpellAbility.playSpellAbility(this,player,sa);
        ctx.log("action","card",sa.getHostCard().getName(),"origin",origin,"api",String.valueOf(sa.getApi()),"accepted",played);
        if(played) {
            if(sa.isActivatedAbility()) activations.merge(chosen,1,Integer::sum);
            failed.clear();
            if(ctx.inspectCopies && sa.isActivatedAbility() && !getGame().getStack().isEmpty() && ctx.snapshotChecks.stream().noneMatch(x->"nonempty-stack".equals(x.get("boundary")))) SnapshotAudit.inspect(getGame(),ctx);
        }
        return played;
    }
    public boolean playSaFromPlayEffect(SpellAbility sa) {
        boolean played=PlaySpellAbility.playSpellAbility(this,player,sa);
        ctx.log("effect-cast","card",sa.getHostCard().getName(),"alternative",String.valueOf(sa.getAlternativeCost()),"accepted",played);
        return played;
    }
    public void playSpellAbilityNoStack(SpellAbility sa,boolean newTargets) {
        if(!PlaySpellAbility.playSpellAbilityNoStack(this,player,sa,!newTargets)) throw new UnsupportedOperationException("mandatory resolution could not be handled: "+sa.getApi());
        if(active) ctx.log("resolved-effect","card",sa.getHostCard().getName(),"api",String.valueOf(sa.getApi()));
    }
    public boolean playTrigger(Card host,WrappedAbility sa,boolean mandatory) {sa.setActivatingPlayer(player);return new PlaySpellAbility(this,sa).playAbility(true,false,false);}
    public void orderAndPlaySimultaneousSa(List<SpellAbility> abilities) {
        List<SpellAbility> ordered=orderSimultaneousSa(abilities);
        for(int i=ordered.size()-1;i>=0;i--) {
            SpellAbility sa=ordered.get(i);sa.setActivatingPlayer(player);
            // Engine-created copies are put on the stack, not cast/paid again.
            // Same lifecycle as PlayerControllerHuman.orderAndPlaySimultaneousSa.
            if(sa.isCopied()) {
                if(sa.isSpell()) {
                    if(!sa.getHostCard().isInZone(ZoneType.Stack))sa.setHostCard(getGame().getAction().moveToStack(sa.getHostCard(),sa));
                    else getGame().getStackZone().add(sa.getHostCard());
                }
                ctx.log("spell-copy","api",String.valueOf(sa.getApi()),"retargeted",false);
                getGame().getStack().add(sa);
            } else if(sa.isTrigger()) {
                if(!PlaySpellAbility.playSpellAbility(this,player,sa))throw new UnsupportedOperationException("trigger setup failed: "+sa.getApi());
            } else getGame().getStack().add(sa);
        }
    }
    public List<SpellAbility> orderSimultaneousSa(List<SpellAbility> list) {ctx.log("trigger-order","apis",list.stream().map(s->String.valueOf(s.getApi())).toList());return list;}
    public boolean confirmTrigger(WrappedAbility sa) {return true;}
    public CostDecisionMakerBase getCostDecisionMaker(Player p,SpellAbility sa,boolean effect,String prompt) {return new GenericCosts(p,sa,effect,this);}
    public List<CostPart> orderCosts(List<CostPart> parts) {return parts;}
    public boolean payManaCost(ManaCost cost,CostPartMana part,SpellAbility sa,String prompt,ManaConversionMatrix matrix,boolean effect) {
        boolean paid=PlaySpellAbility.payManaCost(this,cost,part,sa,player,prompt,matrix,effect);
        if(active && !cost.isZero()) ctx.log("mana-payment","card",sa.getHostCard().getName(),"cost",cost.toString(),"paid",paid);
        return paid;
    }
    public boolean applyManaToCost(ManaCostBeingPaid cost,SpellAbility sa,String prompt,ManaConversionMatrix matrix,boolean effect) {return new ManaPlanner(this,sa).pay(cost,matrix);}

    public double discardScore(Card card) {
        if(card.hasKeyword(Keyword.MADNESS)) return 100;
        if(card.isLand() && player.getCardsIn(ZoneType.Hand).stream().filter(Card::isLand).count()>2) return 50;
        return card.getManaCost().getCMC()-(card.isCommander()?100:0);
    }
    private CardCollection select(CardCollectionView options,int n) {
        if(n<0 || n>options.size()) throw new UnsupportedOperationException("invalid selection bounds");
        List<Card> sorted=new ArrayList<>(options);sorted.sort(Comparator.comparingDouble(this::discardScore).reversed().thenComparingInt(Card::getId));
        return new CardCollection(sorted.subList(0,n));
    }
    public SpellAbility getAbilityToPlay(Card card,List<SpellAbility> options,ITriggerEvent event) {
        if(options.isEmpty()) return null;
        SpellAbility choice=options.stream().max(Comparator.comparingDouble(this::score)).orElseThrow();
        ctx.log("ability-choice","card",card.getName(),"count",options.size(),"chosen_api",String.valueOf(choice.getApi()));return choice;
    }
    public List<AbilitySub> chooseModeForAbility(SpellAbility sa,List<AbilitySub> modes,int min,int max,boolean repeat) {
        List<AbilitySub> sorted=new ArrayList<>(modes);sorted.sort(Comparator.comparingDouble(this::score).reversed());
        List<AbilitySub> chosen=new ArrayList<>();
        for(AbilitySub mode:sorted) if(chosen.size()<min && (!mode.usesTargeting() || !mode.getTargetRestrictions().getAllCandidates(mode).isEmpty())) chosen.add(mode);
        if(chosen.size()<min) throw new UnsupportedOperationException("no handled legal modal selection");
        ctx.log("mode-choice","available",modes.size(),"chosen",chosen.stream().map(s->String.valueOf(s.getApi())).toList());return chosen;
    }
    public boolean chooseTargetsFor(SpellAbility sa) {
        sa.resetTargets();TargetRestrictions tr=sa.getTargetRestrictions();
        int min=tr.getMinTargets(sa.getHostCard(),sa),max=tr.getMaxTargets(sa.getHostCard(),sa);
        List<GameEntity> options=new ArrayList<>(tr.getAllCandidates(sa));
        boolean beneficial=sa.getApi()==ApiType.Draw || sa.getApi()==ApiType.GainLife || sa.getApi()==ApiType.PutCounter || sa.getApi()==ApiType.Pump;
        if(sa.isSpell() && !sa.isCopied() && (sa.getApi()==ApiType.DealDamage || sa.getApi()==ApiType.Destroy)) {
            options.removeIf(e->e instanceof Player?e==player:((Card)e).getController()==player);
            ctx.limitations.add("Default policy declines self-targeted damage/destruction spells; self-damage plans need a goal-aware override");
        }
        options.sort(Comparator.comparingInt(e->(e instanceof Player ? e==player : ((Card)e).getController()==player)==beneficial?0:1));
        int desired=Math.min(max,Math.max(min,options.isEmpty()?0:1));
        for(GameEntity option:options) if(sa.getTargets().size()<desired && sa.canTarget(option)) sa.getTargets().add(option);
        boolean valid=sa.getTargets().size()>=min && sa.getTargets().size()<=max && sa.isTargetNumberValid();
        ctx.log("target-choice","api",String.valueOf(sa.getApi()),"candidates",options.stream().map(GameEntity::getName).toList(),"selected",sa.getTargets().toString(),"valid",valid);return valid;
    }
    public <T extends GameEntity> T chooseSingleEntityForEffect(FCollectionView<T> options,DelayedReveal reveal,SpellAbility sa,String title,boolean optional,Player related,Map<String,Object> params) {
        if(reveal!=null) reveal(reveal);
        if(options.isEmpty()) return null;
        T selected=options.get(0);ctx.log("entity-choice","api",String.valueOf(sa.getApi()),"options",options.stream().map(GameEntity::getName).toList(),"selected",selected.getName());return selected;
    }
    public CardCollectionView chooseCardsForEffect(CardCollectionView options,SpellAbility sa,String title,int min,int max,boolean optional,Map<String,Object> params) {return select(options,min);}
    public Card chooseSingleCardForZoneChange(ZoneType to,List<ZoneType> from,SpellAbility sa,CardCollection options,DelayedReveal reveal,String prompt,boolean optional,Player decider) {
        if(reveal!=null)reveal(reveal);
        if(options.isEmpty())return null;
        Card chosen=options.stream().max(Comparator.comparingDouble(this::acquisitionScore).thenComparingInt(c->-c.getId())).orElseThrow();
        ctx.log("zone-choice","destination",to.toString(),"options",options.stream().map(Card::getName).toList(),"chosen",chosen.getName());return chosen;
    }
    public List<Card> chooseCardsForZoneChange(ZoneType to,List<ZoneType> from,SpellAbility sa,CardCollection options,int min,int max,DelayedReveal reveal,String prompt,Player decider) {
        if(reveal!=null)reveal(reveal);
        if(options.size()<min)throw new UnsupportedOperationException("zone-choice minimum unavailable");
        List<Card> ordered=new ArrayList<>(options);ordered.sort(Comparator.comparingDouble(this::acquisitionScore).reversed().thenComparingInt(Card::getId));
        List<Card> chosen=new ArrayList<>(ordered.subList(0,Math.min(max,ordered.size())));
        ctx.log("zone-choice-multiple","destination",to.toString(),"chosen",chosen.stream().map(Card::getName).toList());return chosen;
    }
    private double acquisitionScore(Card c) {
        long lands=player.getCardsIn(ZoneType.Battlefield).stream().filter(Card::isLand).count();
        if(c.isLand())return lands<4?100:10;
        return (!c.getManaAbilities().isEmpty()?50:25)-c.getManaCost().getCMC();
    }
    public CardCollectionView chooseCardsToDiscardFrom(Player p,SpellAbility sa,CardCollection valid,int min,int max,CardCollectionView visible) {return select(valid,min);}
    public CardCollectionView chooseCardsToDiscardToMaximumHandSize(int n) {return select(player.getCardsIn(ZoneType.Hand),n);}
    public CardCollectionView choosePermanentsToSacrifice(SpellAbility sa,int min,int max,CardCollectionView valid,String message) {return select(valid,min);}
    public CardCollectionView choosePermanentsToDestroy(SpellAbility sa,int min,int max,CardCollectionView valid,String message) {return select(valid,min);}
    public CardCollectionView chooseCardsForCost(CardCollectionView options,SpellAbility sa,CostPartWithList cost,int count,boolean optional,String prompt) {return select(options,count);}
    public ReplacementEffect chooseSingleReplacementEffect(List<ReplacementEffect> options) {if(options.isEmpty())return null;ctx.log("replacement-choice","count",options.size());return options.get(0);}
    public boolean confirmAction(SpellAbility sa,PlayerActionConfirmMode mode,String message,List<String> options,Card card,Map<String,Object> params) {return true;}
    public boolean confirmReplacementEffect(ReplacementEffect effect,SpellAbility sa,GameEntity target,String question) {return true;}
    public boolean confirmStaticApplication(Card card,PlayerActionConfirmMode mode,String message,String logic) {return true;}
    public boolean confirmPayment(CostPart c,String prompt,SpellAbility sa) {return true;}
    public byte chooseColor(String message,SpellAbility sa,ColorSet colours) {
        byte chosen=0;
        if(preferredManaColour!=null && colours.hasAnyColor(preferredManaColour)) chosen=preferredManaColour;
        else for(byte colour:MagicColor.WUBRGC) if(colours.hasAnyColor(colour)) {chosen=colour;break;}
        ctx.log("colour-choice","allowed",colours.toString(),"selected",MagicColor.toShortString(chosen));return chosen;
    }
    public byte chooseColorAllowColorless(String message,Card card,ColorSet colours) {return chooseColor(message,null,colours);}
    public ColorSet chooseColors(String message,SpellAbility sa,int min,int max,ColorSet options) {
        int mask=0,count=0;for(byte c:MagicColor.WUBRGC) if(count<min && options.hasAnyColor(c)) {mask|=c;count++;}
        if(count<min)throw new UnsupportedOperationException("colour-choice bounds");return ColorSet.fromMask(mask);
    }
    public List<OptionalCostValue> chooseOptionalCosts(SpellAbility sa,List<OptionalCostValue> options) {if(!options.isEmpty())ctx.log("declined-optional-costs","count",options.size());return List.of();}
    public List<Card> chooseCardsForSplice(SpellAbility sa,List<Card> cards) {return List.of();}
    public CardCollectionView orderMoveToZoneList(CardCollectionView cards,ZoneType to,SpellAbility sa) {return cards;}
    public ImmutablePair<CardCollection,CardCollection> arrangeForScry(CardCollection cards) {ctx.log("scry","seen",cards.stream().map(Card::getName).toList());return ImmutablePair.of(new CardCollection(cards),new CardCollection());}
    public boolean willPutCardOnTop(Card card) {return true;}
    public boolean chooseBinary(SpellAbility sa,String question,BinaryChoiceType kind,Boolean defaultChoice) {if(defaultChoice!=null)return defaultChoice;throw new UnsupportedOperationException("binary choice without default: "+kind);}
    public int chooseNumber(SpellAbility sa,String title,int min,int max) {ctx.limitations.add("Numeric choices use minimum");return min;}
    public Integer announceRequirements(SpellAbility sa,int min,int max,String kind) {
        if(sa.getPayCosts()!=null && kind.equals("X")) {Integer bound=sa.getPayCosts().getMaxForNonManaX(sa,player,false);if(bound!=null)max=Math.min(max,bound);}
        if(min>max)return null;
        int value=Math.min(max,Math.max(min,kind.equals("X")?1:0));
        ctx.limitations.add("Announced variables use a small fixed heuristic, not searched optimal values");
        ctx.log("announce","variable",kind,"minimum",min,"maximum",max,"selected",value);return value;
    }

    public boolean mulliganKeepHand(Player first,int bottom) {
        long lands=player.getCardsIn(ZoneType.Hand).stream().filter(Card::isLand).count();
        boolean keep=!active || lands>=2 && lands<=5 || mulligans>=2;
        if(active)ctx.log("mulligan","hand",player.getCardsIn(ZoneType.Hand).stream().map(Card::getName).toList(),"bottom",bottom,"keep",keep);
        if(!keep)mulligans++;return keep;
    }
    public CardCollectionView tuckCardsViaMulligan(CardCollectionView hand,int count) {return select(hand,count);}
    public List<PaperCard> sideboard(Deck d,GameType t,String message) {return null;}
    public Player chooseStartingPlayer(boolean first) {return getGame().getPlayers().get(0);}
    public PlayerZone chooseStartingHand(List<PlayerZone> zones) {return zones.get(0);}
    public List<SpellAbility> chooseSaToActivateFromOpeningHand(List<SpellAbility> options) {if(!options.isEmpty())ctx.limitations.add("Opening-hand abilities declined");return List.of();}
    public void reveal(CardCollectionView cards,ZoneType z,Player p,String message,boolean suffix) {}
    public void reveal(List<CardView> cards,ZoneType z,PlayerView p,String message,boolean suffix) {}
    public void revealUnsupported(Map<Player,List<PaperCard>> cards) {if(cards.values().stream().anyMatch(x->!x.isEmpty()))throw new UnsupportedOperationException("unsupported engine cards "+cards);}
    public void notifyOfValue(SpellAbility sa,GameObject object,String value) {}
    public void autoPassCancel() {}
    public void awaitNextInput() {}
    public void cancelAwaitNextInput() {}
    public void declareAttackers(Player p,Combat combat) {}
    public void declareBlockers(Player p,Combat combat) {}
}
