package deckdoctor.spike;
import com.google.common.collect.ListMultimap;
import com.google.common.collect.Lists;
import com.google.common.collect.Multimap;
import forge.LobbyPlayer;
import forge.card.ColorSet;
import forge.card.ICardFace;
import forge.card.mana.ManaCost;
import forge.card.mana.ManaCostShard;
import forge.deck.Deck;
import forge.deck.DeckSection;
import forge.game.*;
import forge.game.GameOutcome.AnteResult;
import forge.game.ability.AbilityUtils;
import forge.game.ability.effects.RollDiceEffect;
import forge.game.card.*;
import forge.game.combat.Combat;
import forge.game.cost.*;
import forge.game.keyword.KeywordInterface;
import forge.game.mana.Mana;
import forge.game.mana.ManaConversionMatrix;
import forge.game.mana.ManaCostBeingPaid;
import forge.game.replacement.ReplacementEffect;
import forge.game.spellability.*;
import forge.game.staticability.StaticAbility;
import forge.game.trigger.WrappedAbility;
import forge.game.zone.PlayerZone;
import forge.game.zone.ZoneType;
import forge.item.PaperCard;
import forge.util.ITriggerEvent;
import forge.util.collect.FCollectionView;
import org.apache.commons.lang3.tuple.ImmutablePair;
import org.apache.commons.lang3.tuple.Pair;
import java.util.Arrays;
import java.util.Collection;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Predicate;
import java.util.stream.Collectors;
import forge.game.player.*;
public class StrictController extends PlayerController {
public StrictController(Game g, Player p, LobbyPlayer l) { super(g,p,l); }
@Override public SpellAbility getAbilityToPlay(Card hostCard, List<SpellAbility> abilities, ITriggerEvent triggerEvent) { throw new UnsupportedOperationException("getAbilityToPlay"); }
@Override public void playSpellAbilityNoStack(SpellAbility effectSA, boolean mayChoseNewTargets) { throw new UnsupportedOperationException("playSpellAbilityNoStack"); }
@Override public List<SpellAbility> orderSimultaneousSa(List<SpellAbility> activePlayerSAs) { throw new UnsupportedOperationException("orderSimultaneousSa"); }
@Override public void orderAndPlaySimultaneousSa(List<SpellAbility> activePlayerSAs) { throw new UnsupportedOperationException("orderAndPlaySimultaneousSa"); }
@Override public boolean playTrigger(Card host, WrappedAbility wrapperAbility, boolean isMandatory) { throw new UnsupportedOperationException("playTrigger"); }
@Override public boolean playSaFromPlayEffect(SpellAbility tgtSA) { throw new UnsupportedOperationException("playSaFromPlayEffect"); }
@Override public List<PaperCard> sideboard(final Deck deck, GameType gameType, String message) { throw new UnsupportedOperationException("sideboard"); }
@Override public List<PaperCard> chooseCardsYouWonToAddToDeck(List<PaperCard> losses) { throw new UnsupportedOperationException("chooseCardsYouWonToAddToDeck"); }
@Override public Map<Card, Integer> assignCombatDamage(Card attacker, CardCollectionView blockers, CardCollectionView remaining, int damageDealt, GameEntity defender, boolean overrideOrder) { throw new UnsupportedOperationException("assignCombatDamage"); }
@Override public Map<GameEntity, Integer> divideShield(Card effectSource, Map<GameEntity, Integer> affected, int shieldAmount) { throw new UnsupportedOperationException("divideShield"); }
@Override public Map<Byte, Integer> specifyManaCombo(SpellAbility sa, ColorSet colorSet, int manaAmount, boolean different) { throw new UnsupportedOperationException("specifyManaCombo"); }
@Override public CardCollectionView choosePermanentsToSacrifice(SpellAbility sa, int min, int max, CardCollectionView validTargets, String message) { throw new UnsupportedOperationException("choosePermanentsToSacrifice"); }
@Override public CardCollectionView choosePermanentsToDestroy(SpellAbility sa, int min, int max, CardCollectionView validTargets, String message) { throw new UnsupportedOperationException("choosePermanentsToDestroy"); }
@Override public Integer announceRequirements(SpellAbility ability, int min, int max, String announce) { throw new UnsupportedOperationException("announceRequirements"); }
@Override public TargetChoices chooseNewTargetsFor(SpellAbility ability, Predicate<GameObject> filter, boolean optional) { throw new UnsupportedOperationException("chooseNewTargetsFor"); }
@Override public boolean chooseTargetsFor(SpellAbility currentAbility) { throw new UnsupportedOperationException("chooseTargetsFor"); }
@Override public Pair<SpellAbilityStackInstance, GameObject> chooseTarget(SpellAbility sa, List<Pair<SpellAbilityStackInstance, GameObject>> allTargets) { throw new UnsupportedOperationException("chooseTarget"); }
@Override public boolean helpPayForAssistSpell(ManaCostBeingPaid cost, SpellAbility sa, int max, int requested) { throw new UnsupportedOperationException("helpPayForAssistSpell"); }
@Override public Player choosePlayerToAssistPayment(FCollectionView<Player> optionList, SpellAbility sa, String title, int max) { throw new UnsupportedOperationException("choosePlayerToAssistPayment"); }
@Override public CardCollectionView chooseCardsForEffect(CardCollectionView sourceList, SpellAbility sa, String title, int min, int max, boolean isOptional, Map<String, Object> params) { throw new UnsupportedOperationException("chooseCardsForEffect"); }
@Override public CardCollection chooseCardsForEffectMultiple(Map<String, CardCollection> validMap, SpellAbility sa, String title, boolean isOptional) { throw new UnsupportedOperationException("chooseCardsForEffectMultiple"); }
@Override public <T extends GameEntity> T chooseSingleEntityForEffect(FCollectionView<T> optionList, DelayedReveal delayedReveal, SpellAbility sa, String title, boolean isOptional, Player relatedPlayer, Map<String, Object> params) { throw new UnsupportedOperationException("chooseSingleEntityForEffect"); }
@Override public <T extends GameEntity> List<T> chooseEntitiesForEffect(FCollectionView<T> optionList, int min, int max, DelayedReveal delayedReveal, SpellAbility sa, String title, Player relatedPlayer, Map<String, Object> params) { throw new UnsupportedOperationException("chooseEntitiesForEffect"); }
@Override public List<SpellAbility> chooseSpellAbilitiesForEffect(List<SpellAbility> spells, SpellAbility sa, String title, int num, Map<String, Object> params) { throw new UnsupportedOperationException("chooseSpellAbilitiesForEffect"); }
@Override public SpellAbility chooseSingleSpellForEffect(List<SpellAbility> spells, SpellAbility sa, String title, Map<String, Object> params) { throw new UnsupportedOperationException("chooseSingleSpellForEffect"); }
@Override public boolean confirmAction(SpellAbility sa, PlayerActionConfirmMode mode, String message, List<String> options, Card cardToShow, Map<String, Object> params) { throw new UnsupportedOperationException("confirmAction"); }
@Override public boolean confirmBidAction(SpellAbility sa, PlayerActionConfirmMode bidlife, String string, int bid, Player winner) { throw new UnsupportedOperationException("confirmBidAction"); }
@Override public boolean confirmReplacementEffect(ReplacementEffect replacementEffect, SpellAbility effectSA, GameEntity affected, String question) { throw new UnsupportedOperationException("confirmReplacementEffect"); }
@Override public boolean confirmStaticApplication(Card hostCard, PlayerActionConfirmMode mode, String message, String logic) { throw new UnsupportedOperationException("confirmStaticApplication"); }
@Override public boolean confirmTrigger(WrappedAbility sa) { throw new UnsupportedOperationException("confirmTrigger"); }
@Override public List<Card> exertAttackers(List<Card> attackers) { throw new UnsupportedOperationException("exertAttackers"); }
@Override public List<Card> enlistAttackers(List<Card> attackers) { throw new UnsupportedOperationException("enlistAttackers"); }
@Override public void declareAttackers(Player attacker, Combat combat) { throw new UnsupportedOperationException("declareAttackers"); }
@Override public void declareBlockers(Player defender, Combat combat) { throw new UnsupportedOperationException("declareBlockers"); }
@Override public CardCollection orderBlockers(Card attacker, CardCollection blockers) { throw new UnsupportedOperationException("orderBlockers"); }
@Override public CardCollection orderBlocker(final Card attacker, final Card blocker, final CardCollection oldBlockers) { throw new UnsupportedOperationException("orderBlocker"); }
@Override public CardCollection orderAttackers(Card blocker, CardCollection attackers) { throw new UnsupportedOperationException("orderAttackers"); }
@Override public void reveal(CardCollectionView cards, ZoneType zone, Player owner, String messagePrefix, boolean addMsgSuffix) { throw new UnsupportedOperationException("reveal"); }
@Override public void reveal(List<CardView> cards, ZoneType zone, PlayerView owner, String messagePrefix, boolean addMsgSuffix) { throw new UnsupportedOperationException("reveal"); }
@Override public void notifyOfValue(SpellAbility saSource, GameObject realtedTarget, String value) { throw new UnsupportedOperationException("notifyOfValue"); }
@Override public ImmutablePair<CardCollection, CardCollection> arrangeForScry(CardCollection topN) { throw new UnsupportedOperationException("arrangeForScry"); }
@Override public ImmutablePair<CardCollection, CardCollection> arrangeForSurveil(CardCollection topN) { throw new UnsupportedOperationException("arrangeForSurveil"); }
@Override public boolean willPutCardOnTop(Card c) { throw new UnsupportedOperationException("willPutCardOnTop"); }
@Override public CardCollectionView orderMoveToZoneList(CardCollectionView cards, ZoneType destinationZone, SpellAbility source) { throw new UnsupportedOperationException("orderMoveToZoneList"); }
@Override public CardCollectionView chooseCardsToDiscardFrom(Player playerDiscard, SpellAbility sa, CardCollection validCards, int min, int max, CardCollectionView visibleToChooser) { throw new UnsupportedOperationException("chooseCardsToDiscardFrom"); }
@Override public CardCollectionView chooseCardsToDiscardUnlessType(int min, CardCollectionView hand, String[] unlessTypes, SpellAbility sa) { throw new UnsupportedOperationException("chooseCardsToDiscardUnlessType"); }
@Override public CardCollectionView chooseCardsToDiscardToMaximumHandSize(int numDiscard) { throw new UnsupportedOperationException("chooseCardsToDiscardToMaximumHandSize"); }
@Override public CardCollectionView chooseCardsToDelve(int genericAmount, CardCollection grave) { throw new UnsupportedOperationException("chooseCardsToDelve"); }
@Override public Map<Card, ManaCostShard> chooseCardsForConvokeOrImprovise(SpellAbility sa, ManaCost manaCost, CardCollectionView untappedCards, boolean artifacts, boolean creatures, Integer maxReduction) { throw new UnsupportedOperationException("chooseCardsForConvokeOrImprovise"); }
@Override public List<Card> chooseCardsForSplice(SpellAbility sa, List<Card> cards) { throw new UnsupportedOperationException("chooseCardsForSplice"); }
@Override public CardCollectionView chooseCardsToRevealFromHand(int min, int max, CardCollectionView valid) { throw new UnsupportedOperationException("chooseCardsToRevealFromHand"); }
@Override public List<SpellAbility> chooseSaToActivateFromOpeningHand(List<SpellAbility> usableFromOpeningHand) { throw new UnsupportedOperationException("chooseSaToActivateFromOpeningHand"); }
@Override public Player chooseStartingPlayer(boolean isFirstGame) { throw new UnsupportedOperationException("chooseStartingPlayer"); }
@Override public PlayerZone chooseStartingHand(List<PlayerZone> zones) { throw new UnsupportedOperationException("chooseStartingHand"); }
@Override public Mana chooseManaFromPool(List<Mana> manaChoices) { throw new UnsupportedOperationException("chooseManaFromPool"); }
@Override public String chooseSomeType(String kindOfType, SpellAbility sa, Collection<String> validTypes, boolean isOptional) { throw new UnsupportedOperationException("chooseSomeType"); }
@Override public String chooseSector(Card assignee, String ai, List<String> sectors) { throw new UnsupportedOperationException("chooseSector"); }
@Override public List<Card> chooseContraptionsToCrank(List<Card> contraptions) { throw new UnsupportedOperationException("chooseContraptionsToCrank"); }
@Override public int chooseSprocket(Card assignee, List<Integer> sprockets) { throw new UnsupportedOperationException("chooseSprocket"); }
@Override public PlanarDice choosePDRollToIgnore(List<PlanarDice> rolls) { throw new UnsupportedOperationException("choosePDRollToIgnore"); }
@Override public Integer chooseRollToIgnore(List<Integer> rolls) { throw new UnsupportedOperationException("chooseRollToIgnore"); }
@Override public List<Integer> chooseDiceToReroll(List<Integer> rolls) { throw new UnsupportedOperationException("chooseDiceToReroll"); }
@Override public Integer chooseRollToModify(List<Integer> rolls) { throw new UnsupportedOperationException("chooseRollToModify"); }
@Override public RollDiceEffect.DieRollResult chooseRollToSwap(List<RollDiceEffect.DieRollResult> rolls) { throw new UnsupportedOperationException("chooseRollToSwap"); }
@Override public String chooseRollSwapValue(List<String> swapChoices, Integer currentResult, int power, int toughness) { throw new UnsupportedOperationException("chooseRollSwapValue"); }
@Override public Object vote(SpellAbility sa, String prompt, List<Object> options, ListMultimap<Object, Player> votes, Player forPlayer, boolean optional) { throw new UnsupportedOperationException("vote"); }
@Override public boolean mulliganKeepHand(Player player, int cardsToReturn) { throw new UnsupportedOperationException("mulliganKeepHand"); }
@Override public CardCollectionView tuckCardsViaMulligan(CardCollectionView hand, int cardsToReturn) { throw new UnsupportedOperationException("tuckCardsViaMulligan"); }
@Override public List<SpellAbility> chooseSpellAbilityToPlay() { throw new UnsupportedOperationException("chooseSpellAbilityToPlay"); }
@Override public boolean playChosenSpellAbility(SpellAbility sa) { throw new UnsupportedOperationException("playChosenSpellAbility"); }
@Override public List<AbilitySub> chooseModeForAbility(SpellAbility sa, List<AbilitySub> possible, int min, int num, boolean allowRepeat) { throw new UnsupportedOperationException("chooseModeForAbility"); }
@Override public int chooseNumberForCostReduction(final SpellAbility sa, final int min, final int max) { throw new UnsupportedOperationException("chooseNumberForCostReduction"); }
@Override public int chooseNumberForKeywordCost(SpellAbility sa, Cost cost, KeywordInterface keyword, String prompt, int max) { throw new UnsupportedOperationException("chooseNumberForKeywordCost"); }
@Override public int chooseNumber(SpellAbility sa, String title, int min, int max) { throw new UnsupportedOperationException("chooseNumber"); }
@Override public int chooseNumber(SpellAbility sa, String title, List<Integer> values, Player relatedPlayer) { throw new UnsupportedOperationException("chooseNumber"); }
@Override public boolean chooseBinary(SpellAbility sa, String question, BinaryChoiceType kindOfChoice, Boolean defaultChoice) { throw new UnsupportedOperationException("chooseBinary"); }
@Override public boolean chooseFlipResult(SpellAbility sa, Player flipper, boolean call) { throw new UnsupportedOperationException("chooseFlipResult"); }
@Override public byte chooseColor(String message, SpellAbility sa, ColorSet colors) { throw new UnsupportedOperationException("chooseColor"); }
@Override public byte chooseColorAllowColorless(String message, Card c, ColorSet colors) { throw new UnsupportedOperationException("chooseColorAllowColorless"); }
@Override public ColorSet chooseColors(String message, SpellAbility sa, int min, int max, ColorSet options) { throw new UnsupportedOperationException("chooseColors"); }
@Override public ICardFace chooseSingleCardFace(SpellAbility sa, String message, Predicate<ICardFace> cpp, String name) { throw new UnsupportedOperationException("chooseSingleCardFace"); }
@Override public ICardFace chooseSingleCardFace(SpellAbility sa, List<ICardFace> faces, String message) { throw new UnsupportedOperationException("chooseSingleCardFace"); }
@Override public CardState chooseSingleCardState(SpellAbility sa, List<CardState> states, String message, Map<String, Object> params) { throw new UnsupportedOperationException("chooseSingleCardState"); }
@Override public boolean chooseCardsPile(SpellAbility sa, CardCollectionView pile1, CardCollectionView pile2, String faceUp) { throw new UnsupportedOperationException("chooseCardsPile"); }
@Override public CounterType chooseCounterType(List<CounterType> options, SpellAbility sa, String prompt, Map<String, Object> params) { throw new UnsupportedOperationException("chooseCounterType"); }
@Override public String chooseKeywordForPump(List<String> options, SpellAbility sa, String prompt, Card tgtCard) { throw new UnsupportedOperationException("chooseKeywordForPump"); }
@Override public boolean confirmPayment(CostPart costPart, String string, SpellAbility sa) { throw new UnsupportedOperationException("confirmPayment"); }
@Override public ReplacementEffect chooseSingleReplacementEffect(List<ReplacementEffect> possibleReplacers) { throw new UnsupportedOperationException("chooseSingleReplacementEffect"); }
@Override public StaticAbility chooseSingleStaticAbility(List<StaticAbility> possibleReplacers) { throw new UnsupportedOperationException("chooseSingleStaticAbility"); }
@Override public String chooseProtectionType(SpellAbility sa, List<String> choices) { throw new UnsupportedOperationException("chooseProtectionType"); }
@Override public void revealAnte(String message, Multimap<Player, PaperCard> removedAnteCards) { throw new UnsupportedOperationException("revealAnte"); }
@Override public void revealAISkipCards(String message, Map<Player, Map<DeckSection, List<? extends PaperCard>>> deckCards) { throw new UnsupportedOperationException("revealAISkipCards"); }
@Override public void revealUnsupported(Map<Player, List<PaperCard>> unsupported) { throw new UnsupportedOperationException("revealUnsupported"); }
@Override public List<OptionalCostValue> chooseOptionalCosts(SpellAbility choosen, List<OptionalCostValue> optionalCostValues) { throw new UnsupportedOperationException("chooseOptionalCosts"); }
@Override public List<CostPart> orderCosts(List<CostPart> costs) { throw new UnsupportedOperationException("orderCosts"); }
@Override public boolean payCostToPreventEffect(Cost cost, SpellAbility sa, boolean alreadyPaid, FCollectionView<Player> allPayers) { throw new UnsupportedOperationException("payCostToPreventEffect"); }
@Override public boolean payCostDuringRoll(Cost cost, SpellAbility sa) { throw new UnsupportedOperationException("payCostDuringRoll"); }
@Override public boolean payCombatCost(Card card, Cost cost, SpellAbility sa, String prompt) { throw new UnsupportedOperationException("payCombatCost"); }
@Override public boolean payManaCost(ManaCost toPay, CostPartMana costPartMana, SpellAbility sa, String prompt, ManaConversionMatrix matrix, boolean effect) { throw new UnsupportedOperationException("payManaCost"); }
@Override public boolean applyManaToCost(ManaCostBeingPaid toPay, SpellAbility ability, String prompt, ManaConversionMatrix matrix, boolean effect) { throw new UnsupportedOperationException("applyManaToCost"); }
@Override public CardCollectionView chooseCardsForCost(CardCollectionView optionList, SpellAbility sa, CostPartWithList cpl, int amount, boolean isOptional, String prompt) { throw new UnsupportedOperationException("chooseCardsForCost"); }
@Override public CostDecisionMakerBase getCostDecisionMaker(Player player, SpellAbility ability, boolean effect, String prompt) { throw new UnsupportedOperationException("getCostDecisionMaker"); }
@Override public String chooseCardName(SpellAbility sa, Predicate<ICardFace> cpp, String valid, String message) { throw new UnsupportedOperationException("chooseCardName"); }
@Override public String chooseCardName(SpellAbility sa, List<ICardFace> faces, String message) { throw new UnsupportedOperationException("chooseCardName"); }
@Override public Card chooseSingleCardForZoneChange(ZoneType destination, List<ZoneType> origin, SpellAbility sa, CardCollection fetchList, DelayedReveal delayedReveal, String selectPrompt, boolean isOptional, Player decider) { throw new UnsupportedOperationException("chooseSingleCardForZoneChange"); }
@Override public List<Card> chooseCardsForZoneChange(ZoneType destination, List<ZoneType> origin, SpellAbility sa, CardCollection fetchList, int min, int max, DelayedReveal delayedReveal, String selectPrompt, Player decider) { throw new UnsupportedOperationException("chooseCardsForZoneChange"); }
@Override public void autoPassCancel() { throw new UnsupportedOperationException("autoPassCancel"); }
@Override public void awaitNextInput() { throw new UnsupportedOperationException("awaitNextInput"); }
@Override public void cancelAwaitNextInput() { throw new UnsupportedOperationException("cancelAwaitNextInput"); }
}
