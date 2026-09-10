package deckdoctor.spike;

import com.google.common.eventbus.Subscribe;
import forge.*;
import forge.gui.GuiBase;
import forge.model.FModel;
import forge.deck.*;
import forge.game.*;
import forge.game.card.*;
import forge.game.combat.Combat;
import forge.game.cost.*;
import forge.game.event.GameEventTurnBegan;
import forge.game.event.GameEventCardChangeZone;
import forge.game.mana.*;
import forge.game.player.*;
import forge.game.spellability.*;
import forge.game.trigger.WrappedAbility;
import forge.game.zone.*;
import forge.card.mana.ManaCost;
import forge.item.PaperCard;
import forge.util.*;
import java.util.*;

/** Bounded feasibility probe. Unsupported decisions abort, never fall back to AI. */
public class EngineOnlyProbe {
    static int turns, casts, triggers, mulligans;
    static boolean finished;
    static boolean wrongColour;
    static String scenario;
    static int commanderTurn, resolvedDraws;
    static int madnessCasts, untapTriggers;
    static int normalDraws, effectDraws, madnessPayments;
    static long start;

    static class Seat extends LobbyPlayer implements IGameEntitiesFactory {
        final boolean active;
        Seat(String name, boolean active) { super(name); this.active = active; }
        public Player createIngamePlayer(Game g, int id) {
            Player p = new Player(getName(),g,id);
            p.setFirstController(new Controller(g,p,this,active)); return p;
        }
        public PlayerController createMindSlaveController(Player master, Player slave) {
            throw new UnsupportedOperationException("mind control");
        }
        public void hear(LobbyPlayer p, String message) {}
    }

    static class Controller extends StrictController {
        final boolean active;
        int attempts;
        int activatedTurn;
        Set<String> tried = new HashSet<>();
        Controller(Game g,Player p,LobbyPlayer l,boolean active) {super(g,p,l);this.active=active;}
        public List<PaperCard> sideboard(Deck d,GameType t,String message) {return null;}
        public Player chooseStartingPlayer(boolean first) {return getGame().getPlayers().get(0);}
        public PlayerZone chooseStartingHand(List<PlayerZone> zones) {return zones.get(0);}
        public List<SpellAbility> chooseSaToActivateFromOpeningHand(List<SpellAbility> a) {return List.of();}
        public boolean mulliganKeepHand(Player first,int bottom) {
            long lands=player.getCardsIn(ZoneType.Hand).stream().filter(Card::isLand).count();
            boolean keep=!active || (lands>=2 && lands<=5) || attempts>=2;
            if(active) System.out.println("MULLIGAN hand="+player.getCardsIn(ZoneType.Hand)+" bottom="+bottom+" keep="+keep);
            if(!keep) {attempts++;mulligans++;} return keep;
        }
        public CardCollectionView tuckCardsViaMulligan(CardCollectionView hand,int count) {
            CardCollection result=new CardCollection();
            for(Card c:hand) if(result.size()<count) result.add(c);
            return result;
        }
        public void reveal(CardCollectionView c,ZoneType z,Player p,String m,boolean suffix) {}
        public void reveal(List<CardView> c,ZoneType z,PlayerView p,String m,boolean suffix) {}
        public void revealUnsupported(Map<Player,List<PaperCard>> cards) {
            if(cards.values().stream().anyMatch(x->!x.isEmpty())) throw new UnsupportedOperationException("unsupported cards "+cards);
        }
        public void notifyOfValue(SpellAbility s,GameObject o,String v) {}
        public void autoPassCancel() {}
        public void awaitNextInput() {}
        public void cancelAwaitNextInput() {}
        public void declareAttackers(Player p,Combat c) {}
        public void declareBlockers(Player p,Combat c) {}
        public List<SpellAbility> chooseSpellAbilityToPlay() {
            if(!active || getGame().getPhaseHandler().getPlayerTurn()!=player || !getGame().getPhaseHandler().getPhase().isMain() || !getGame().getStack().isEmpty()) return null;
            if(++priorityCalls>5000) throw new IllegalStateException("priority loop");
            List<Card> cards=new ArrayList<>();
            cards.addAll(player.getCardsIn(ZoneType.Hand));
            cards.addAll(player.getCardsIn(ZoneType.Command));
            if(scenario.equals("anje") && activatedTurn!=turns)
                for(Card c:player.getCardsIn(ZoneType.Battlefield))
                    if(c.getName().equals("Anje Falkenrath") && player.getCardsIn(ZoneType.Hand).stream().anyMatch(x->x.getName().equals("Kitchen Imp"))) cards.add(c);
            cards.sort(Comparator.comparingInt(c->c.isLand()?0:c.isCommander()?1:2));
            for(Card c:cards) for(SpellAbility sa:c.getAllPossibleAbilities(player,true)) {
                boolean outlet=scenario.equals("anje") && c.isInZone(ZoneType.Battlefield) && c.getName().equals("Anje Falkenrath") && sa.getApi()==forge.game.ability.ApiType.Draw;
                if(!sa.isSpell() && !sa.isLandAbility() && !outlet) continue;
                if(scenario.equals("anje") && sa.isSpell() && c.getName().equals("Kitchen Imp")) continue; // reserve for madness
                sa.setActivatingPlayer(player);
                String key=getGame().getPhaseHandler().getTurn()+":"+c.getId()+":"+sa.toString();
                if(sa.canPlay() && !tried.contains(key)) {tried.add(key);return List.of(sa);}
            }
            return null;
        }
        int priorityCalls;
        public boolean playChosenSpellAbility(SpellAbility sa) {
            boolean result=PlaySpellAbility.playSpellAbility(this,player,sa);
            System.out.println("ACTION turn="+turns+" card="+sa.getHostCard().getName()+" accepted="+result+" pool="+player.getManaPool());
            if(result && sa.isSpell()) casts++;
            if(result && sa.getHostCard().isCommander() && sa.isSpell()) commanderTurn=turns;
            if(result && sa.isActivatedAbility() && sa.getHostCard().getName().equals("Anje Falkenrath")) activatedTurn=turns;
            if(result) tried.clear();
            return result;
        }
        public SpellAbility getAbilityToPlay(Card c,List<SpellAbility> choices,ITriggerEvent event) {
            if(choices.size()!=1) throw new UnsupportedOperationException("multiple ability choices "+choices);
            return choices.get(0);
        }
        public List<OptionalCostValue> chooseOptionalCosts(SpellAbility s,List<OptionalCostValue> v) {return List.of();}
        public List<Card> chooseCardsForSplice(SpellAbility s,List<Card> c) {return List.of();}
        public CostDecisionMakerBase getCostDecisionMaker(Player p,SpellAbility sa,boolean effect,String prompt) {return new StrictCosts(p,sa,effect);}
        public List<CostPart> orderCosts(List<CostPart> parts) {return parts;}
        public boolean payManaCost(ManaCost cost,CostPartMana part,SpellAbility sa,String prompt,ManaConversionMatrix matrix,boolean effect) {
            boolean paid=PlaySpellAbility.payManaCost(this,cost,part,sa,player,prompt,matrix,effect);
            if(sa.getHostCard().getName().equals("Kitchen Imp") && !cost.isZero()) {
                System.out.println("MADNESS_PAYMENT cost="+cost+" paid="+paid);
                if(paid && cost.getCMC()==1) madnessPayments++;
            }
            return paid;
        }
        public boolean applyManaToCost(ManaCostBeingPaid cost,SpellAbility sa,String prompt,ManaConversionMatrix matrix,boolean effect) {
            player.getManaPool().applyCardMatrix(matrix);
            // Plan against a copy, so an unaffordable attempt never taps real sources.
            ManaCostBeingPaid preview=new ManaCostBeingPaid(cost);
            for(Mana floating:player.getManaPool()) if(floating.meetsManaRestrictions(sa) && preview.isNeeded(floating,player.getManaPool())) preview.payMana(floating,player.getManaPool());
            List<SpellAbility> plan=new ArrayList<>();
            for(Card c:player.getCardsIn(ZoneType.Battlefield)) {
                if(preview.isPaid()) break;
                for(SpellAbility mana:c.getManaAbilities()) {
                    mana.setActivatingPlayer(player);
                    if(!mana.canPlay() || !mana.getPayCosts().getCostParts().stream().allMatch(x -> x instanceof CostTap)) continue;
                    String output=mana.getParamOrDefault("Produced","");
                    if(!output.matches("[WUBRGC]") || !mana.getParamOrDefault("Amount","1").equals("1")) throw new UnsupportedOperationException("non-simple mana "+mana);
                    Mana token=new Mana(forge.card.MagicColor.fromName(output),c,mana.getManaPart(),player);
                    if(token.meetsManaRestrictions(sa) && preview.isNeeded(token,player.getManaPool())) {preview.payMana(token,player.getManaPool());plan.add(mana);break;}
                }
            }
            if(!preview.isPaid()) return false;
            if(player.getManaPool().payManaCostFromPool(cost,sa,false,new ArrayList<>())) return true;
            // Bounded policy: only plain fixed-output tap mana abilities. Engine pays costs and adds mana.
            for(SpellAbility mana:plan) {
                if(!PlaySpellAbility.playSpellAbility(this,player,mana)) throw new IllegalStateException("planned mana failed");
                player.getManaPool().payManaFromAbility(sa,cost,mana);
                if(cost.isPaid()) return true;
            }
            return cost.isPaid();
        }
        public List<SpellAbility> orderSimultaneousSa(List<SpellAbility> a) {return a;}
        public forge.game.replacement.ReplacementEffect chooseSingleReplacementEffect(List<forge.game.replacement.ReplacementEffect> options) {
            if(options.size()!=1) throw new UnsupportedOperationException("multiple replacement effects "+options);
            return options.get(0);
        }
        public boolean playSaFromPlayEffect(SpellAbility sa) {
            boolean result=PlaySpellAbility.playSpellAbility(this,player,sa);
            System.out.println("EFFECT_CAST "+sa.getHostCard().getName()+" cost="+sa.getPayCosts()+" accepted="+result);
            if(result && sa.getHostCard().getName().equals("Kitchen Imp")) madnessCasts++;
            return result;
        }
        public <T extends GameEntity> T chooseSingleEntityForEffect(forge.util.collect.FCollectionView<T> options,DelayedReveal reveal,SpellAbility sa,String title,boolean optional,Player related,Map<String,Object> params) {
            if(options.size()!=1) throw new UnsupportedOperationException("multiple effect choices "+options);
            return options.get(0);
        }
        public boolean confirmAction(SpellAbility sa,PlayerActionConfirmMode mode,String message,List<String> options,Card card,Map<String,Object> params) {
            if(!scenario.equals("anje")) throw new UnsupportedOperationException("confirmAction "+message);
            return true;
        }
        public void playSpellAbilityNoStack(SpellAbility sa,boolean newTargets) {
            if(!PlaySpellAbility.playSpellAbilityNoStack(this,player,sa,!newTargets))
                throw new IllegalStateException("trigger resolution payment failed: "+sa);
            System.out.println("RESOLVED "+sa.getHostCard().getName()+" effect="+sa.getApi()+" hand="+player.getCardsIn(ZoneType.Hand).size());
            if(active && sa.getApi()==forge.game.ability.ApiType.Draw) resolvedDraws++;
            if(active && sa.getApi()==forge.game.ability.ApiType.Untap && sa.getHostCard().getName().equals("Anje Falkenrath")) untapTriggers++;
        }
        public void orderAndPlaySimultaneousSa(List<SpellAbility> a) {
            for(SpellAbility sa:a) {sa.setActivatingPlayer(player);new PlaySpellAbility(this,sa).playAbility(true,false,false);triggers++;}
        }
        public boolean playTrigger(Card host,WrappedAbility ability,boolean mandatory) {
            ability.setActivatingPlayer(player);triggers++;
            return new PlaySpellAbility(this,ability).playAbility(true,false,false);
        }
        public boolean confirmTrigger(WrappedAbility a) {return true;}
        public CardCollectionView chooseCardsToDiscardToMaximumHandSize(int n) {
            CardCollection c=new CardCollection();for(Card x:player.getCardsIn(ZoneType.Hand)) if(c.size()<n)c.add(x);return c;
        }
        public CardCollectionView orderMoveToZoneList(CardCollectionView c,ZoneType z,SpellAbility s) {return c;}
    }

    public static class Cap {
        final Game game;
        Cap(Game g) {game=g;}
        @Subscribe public void onZone(GameEventCardChangeZone event) {
            if(game.getAge()!=GameStage.Play || event.from()==null || event.to()==null || event.to().player()==null) return;
            if(event.to().player().getId()!=game.getPlayers().get(0).getId()) return;
            if(event.from().zoneType()==ZoneType.Library && event.to().zoneType()==ZoneType.Hand) {
                boolean normal=game.getPhaseHandler().getPhase()==forge.game.phase.PhaseType.DRAW;
                if(normal) normalDraws++;else effectDraws++;
                System.out.println("DRAW turn="+turns+" kind="+(normal?"turn":"effect")+" card="+event.card().getName());
            }
        }
        @Subscribe public void onTurn(GameEventTurnBegan event) {
            if(game.getPhaseHandler().getPlayerTurn()!=game.getPlayers().get(0)) return;
            turns++;
            Player p=game.getPlayers().get(0);
            System.out.println("TURN "+turns+" hand="+p.getCardsIn(ZoneType.Hand)+" board="+p.getCardsIn(ZoneType.Battlefield));
            if(turns==7) {finished=true;game.setGameOver(GameEndReason.Draw);}
        }
    }
    static Deck deck(boolean active) {
        Deck d=new Deck(active?"probe":"passive");
        if(active && scenario.equals("anje")) {
            d.getOrCreate(DeckSection.Commander).add(card("Anje Falkenrath"),1);
            d.getMain().add(card("Swamp"),19);d.getMain().add(card("Mountain"),18);
            d.getMain().add(card("Kitchen Imp"),62);return d;
        }
        d.getOrCreate(DeckSection.Commander).add(card("Isamaru, Hound of Konda"),1);
        String land=active && wrongColour ? "Island" : active && scenario.equals("tapped") ? "Secluded Steppe" : "Plains";
        int lands=active ? scenario.equals("mulligan") ? 99 : 37 : 99;
        d.getMain().add(card(land),lands);
        if(active && lands==37) { d.getMain().add(card("Wall of Omens"),20); d.getMain().add(card("Savannah Lions"),20); d.getMain().add(card("Revitalize"),22); }
        return d;
    }
    static PaperCard card(String name) {return Objects.requireNonNull(StaticData.instance().getCommonCards().getCard(name),name);}
    public static void main(String[] args) throws Exception {
        GuiBase.setInterface(new GuiDesktop());FModel.initialize(null,null);
        Thread.setDefaultUncaughtExceptionHandler((thread,error)->{error.printStackTrace(System.err);System.exit(1);});
        StaticData.instance().setMulliganRule(MulliganDefs.MulliganRule.London);
        String mode=args.length>0 ? args[0] : "draw";
        for(String test:mode.equals("suite") ? List.of("draw","wrong-colour","tapped","mulligan","anje") : List.of(mode)) runCase(test);
    }
    static void runCase(String test) {
        scenario=test;wrongColour=test.equals("wrong-colour");
        turns=casts=triggers=mulligans=commanderTurn=resolvedDraws=madnessCasts=untapTriggers=normalDraws=effectDraws=madnessPayments=0;finished=false;
        System.out.println("SCENARIO "+scenario+" synthetic mechanics fixture, not a legal singleton deck");
        MyRandom.setRandom(new Random(42));
        GameRules rules=new GameRules(GameType.Commander);
        rules.setAppliedVariants(EnumSet.of(GameType.Commander));rules.setSimTimeout(30);
        List<RegisteredPlayer> seats=new ArrayList<>();
        for(int i=0;i<3;i++) seats.add(RegisteredPlayer.forCommander(deck(i==0)).setPlayer(new Seat("seat-"+i,i==0)));
        Match match=new Match(rules,seats,"engine-only");Game game=match.createGame();
        game.subscribeToEvents(new Cap(game));start=System.nanoTime();
        match.startGame(game);
        if(!finished) throw new IllegalStateException("did not complete six turns");
        if(normalDraws!=6) throw new IllegalStateException("expected six normal draws, got "+normalDraws);
        if(wrongColour && casts!=0) throw new IllegalStateException("cast a white spell using only Islands");
        if(test.equals("draw") && (resolvedDraws==0 || commanderTurn==0)) throw new IllegalStateException("did not execute draw + commander plan");
        if(test.equals("tapped") && (commanderTurn<=1 || resolvedDraws==0)) throw new IllegalStateException("tapped lands/draw check failed");
        if(test.equals("mulligan") && mulligans!=2) throw new IllegalStateException("mulligan check failed");
        if(test.equals("anje") && (madnessCasts==0 || untapTriggers==0 || madnessPayments!=madnessCasts)) throw new IllegalStateException("madness plan did not execute with real payments");
        if(test.equals("anje") && game.getPlayers().get(0).getCardsIn(ZoneType.Battlefield).stream().filter(c->c.getName().equals("Kitchen Imp")).count()!=madnessCasts) throw new IllegalStateException("madness spells did not resolve onto battlefield");
        System.out.println("PROBE_OK scenario="+scenario+" normal_draws="+normalDraws+" effect_draws="+effectDraws+" casts="+casts+" resolved_draw_triggers="+resolvedDraws+" commander_turn="+commanderTurn+" mulligans="+mulligans+" madness_casts="+madnessCasts+" untap_triggers="+untapTriggers+" elapsed_ms="+(System.nanoTime()-start)/1e6);
    }
}
