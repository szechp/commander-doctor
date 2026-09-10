package deckdoctor.generic;

import com.google.common.eventbus.Subscribe;
import forge.*;
import forge.gui.GuiBase;
import forge.model.FModel;
import forge.deck.*;
import forge.game.*;
import forge.game.card.*;
import forge.game.event.*;
import forge.game.player.*;
import forge.game.zone.ZoneType;
import forge.game.phase.PhaseType;
import forge.item.PaperCard;
import forge.util.MyRandom;
import java.nio.file.*;
import java.util.*;
import java.util.regex.*;

public final class GenericProbe {
    static final Pattern LINE=Pattern.compile("^(\\d+)\\s+(.+?)(?:\\s+\\([A-Za-z0-9]+\\)\\s+\\S+)?$");
    static final class Seat extends LobbyPlayer implements IGameEntitiesFactory {
        final RunContext context;final boolean active;
        Seat(String name,RunContext context,boolean active) {super(name);this.context=context;this.active=active;}
        public Player createIngamePlayer(Game game,int id) {Player p=new Player(getName(),game,id);p.setFirstController(new GenericController(game,p,this,context,active));return p;}
        public PlayerController createMindSlaveController(Player master,Player slave) {throw new UnsupportedOperationException("mind control");}
        public void hear(LobbyPlayer p,String message) {}
    }
    public static final class Observer {
        final Game game;final RunContext ctx;
        Observer(Game game,RunContext ctx) {this.game=game;this.ctx=ctx;}
        @Subscribe public void turn(GameEventTurnBegan event) {
            if(game.getPhaseHandler().getPlayerTurn()!=game.getPlayers().get(0))return;
            ctx.turn++;
            if(ctx.turn==7) {ctx.finished=true;game.setGameOver(GameEndReason.Draw);}
        }
        @Subscribe public void zone(GameEventCardChangeZone event) {
            if(game.getAge()!=GameStage.Play || event.from()==null || event.to()==null || event.to().player()==null || event.to().player().getId()!=game.getPlayers().get(0).getId()) return;
            ZoneType from=event.from().zoneType(),to=event.to().zoneType();
            Card card=game.findById(event.card().getId());
            ctx.log("zone","card",event.card().getName(),"from",from.toString(),"to",to.toString());
            if(from==ZoneType.Library && to==ZoneType.Hand) {
                if(game.getPhaseHandler().getPhase()==PhaseType.DRAW)ctx.normalDraws++;
                else {ctx.effectDraws++;ctx.event("effect_draw");}
            }
            if(from==ZoneType.Stack && to==ZoneType.Battlefield) {
                ctx.event("permanent_resolved");
                if(card!=null && card.isCommander())ctx.event("commander_resolved");
                if(card!=null && card.getCastSA()!=null && card.getCastSA().getAlternativeCost()!=null)ctx.event("alternative_permanent_resolved");
            }
        }
    }
    static PaperCard card(String name) {return Objects.requireNonNull(StaticData.instance().getCommonCards().getCard(name),"unresolved engine card: "+name);}
    static Deck load(Path path) throws Exception {
        Deck deck=new Deck(path.getFileName().toString());int total=0;boolean first=true;
        for(String raw:Files.readAllLines(path)) {
            String line=raw.strip();if(line.isEmpty() || line.startsWith("//"))continue;
            Matcher match=LINE.matcher(line);if(!match.matches())throw new IllegalArgumentException("unparsed line: "+line);
            int n=Integer.parseInt(match.group(1));if(n<=0 || first && n!=1)throw new IllegalArgumentException("invalid count: "+line);
            PaperCard card=card(match.group(2));deck.getOrCreate(first?DeckSection.Commander:DeckSection.Main).add(card,n);first=false;total+=n;
        }
        if(total!=100)throw new IllegalArgumentException("expected 100 cards, got "+total);return deck;
    }
    static Deck passive() {Deck d=new Deck("passive");d.getOrCreate(DeckSection.Commander).add(card("Isamaru, Hound of Konda"),1);d.getMain().add(card("Plains"),99);return d;}
    static Map<String,Object> run(Deck deck,long seed,Map<String,Integer> requirements,boolean copies,String branch) {
        RunContext ctx=new RunContext(seed,requirements,copies);Game game=null;long start=System.nanoTime();
        if(!branch.isEmpty()) {String[] parts=branch.split(":");ctx.branchDecision=Integer.parseInt(parts[0]);ctx.branchIndex=Integer.parseInt(parts[1]);}
        try {
            MyRandom.setRandom(new Random(seed));
            GameRules rules=new GameRules(GameType.Commander);rules.setAppliedVariants(EnumSet.of(GameType.Commander));rules.setSimTimeout(30);
            List<RegisteredPlayer> players=new ArrayList<>();
            for(int i=0;i<3;i++)players.add(RegisteredPlayer.forCommander(i==0?deck:passive()).setPlayer(new Seat("seat-"+i,ctx,i==0)));
            Match match=new Match(rules,players,"generic-engine-probe");game=match.createGame();game.subscribeToEvents(new Observer(game,ctx));
            match.startGame(game);
            if(ctx.finished && ctx.normalDraws!=6)throw new IllegalStateException("expected six normal draws, got "+ctx.normalDraws);
        } catch(Exception e) {ctx.error=e.getClass().getSimpleName()+": "+e.getMessage();ctx.failureStatus=e instanceof UnsupportedOperationException?"unsupported":"error";ctx.log(ctx.failureStatus,"reason",ctx.error);}
        return ctx.result(game,deck.getName(),System.nanoTime()-start);
    }
    public static void main(String[] args) throws Exception {
        GuiBase.setInterface(new GuiDesktop());FModel.initialize(null,null);
        Thread.setDefaultUncaughtExceptionHandler((t,e)->{e.printStackTrace(System.err);System.exit(1);});
        StaticData.instance().setMulliganRule(MulliganDefs.MulliganRule.London);
        Path request=Path.of(args[0]),output=Path.of(args[1]);
        List<Object> results=new ArrayList<>();
        for(String line:Files.readAllLines(request)) {
            if(line.isBlank())continue;
            String[] fields=line.split("\\t",-1);
            String deckPath=fields[0];long seed=Long.parseLong(fields[1]);boolean copies=Boolean.parseBoolean(fields[2]);
            Map<String,Integer> requirements=new TreeMap<>();
            if(fields.length>3 && !fields[3].isEmpty())for(String pair:fields[3].split(",")) {String[] kv=pair.split("=");requirements.put(kv[0],Integer.parseInt(kv[1]));}
            try {
                Map<String,Object> result=run(load(Path.of(deckPath)),seed,requirements,copies,fields.length>4?fields[4]:"");
                results.add(result);
                System.out.println("GENERIC_RESULT "+result.get("deck")+" "+result.get("status")+" draws="+result.get("normal_draws")+" extra="+result.get("effect_draws")+" events="+result.get("events")+" error="+result.get("error"));
            } catch(Exception e) {results.add(Map.of("deck",deckPath,"status","input_error","error",e.toString()));}
            Files.writeString(output,Json.write(Map.of("results",results)));
        }
    }
}
