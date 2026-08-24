/**
 * "How to use ASPIRE AI", in the three languages the product ships.
 *
 * Data, not JSX: one structure per locale, so the panel renders whichever the
 * reader has chosen and a translator can work in this one file. Inline
 * emphasis is written as **bold** and *italic* and rendered by the panel.
 */

import type { Locale } from "./i18n";

export interface HelpSection {
	title: string;
	glyph?: "person" | "spark" | "mic" | "shuffle";
	paras: string[];
	list?: string[];
	can?: { label: string; items: string[] };
	cannot?: { label: string; items: string[] };
	note?: string;
	guides?: boolean;
}

export interface HelpCopy {
	title: string;
	lede: string;
	sections: HelpSection[];
	/** Localised audience + blurb per guide id, for the guides list. */
	guideRows: Record<string, { audience: string; blurb: string }>;
}

const EN: HelpCopy = {
	title: "How to use ASPIRE AI",
	lede: "ASPIRE AI is the assistant for the ASPIRE Programme, a Government of St Kitts and Nevis initiative. It explains what the programme is, helps with joining it, and teaches how saving and money work.",
	guideRows: {},
	sections: [
		{
			title: "Who it is for",
			paras: [
				"Young people aged 5 to 18, and the parents, guardians and teachers helping them. You do not need an account to ask a question — signing in is only needed to apply, or to keep your lessons between visits.",
			],
		},
		{
			title: "Who you are talking to",
			glyph: "person",
			guides: true,
			paras: [
				"Choosing a persona changes how ASPIRE AI writes to you: the words it picks, how long an answer is, and whether it explains or gets to the point. It is not just a label — the same question genuinely gets a different answer.",
			],
			note: "**To switch:** use the person button at the bottom of the screen, next to where you type. You can change it at any time, as often as you like.",
		},
		{
			title: "Explain it simply",
			glyph: "spark",
			paras: [
				"Two ways to get a plainer version of the same answer. The **Explain it simply** button beside the text box keeps every new answer short and simple until you switch it off. Or press **Simpler** underneath any answer already on screen to have that one said again in easier words.",
			],
			note: "It changes the wording, never the facts — the figures, rules and sources stay exactly as they were.",
		},
		{
			title: "Listening and speaking",
			glyph: "mic",
			paras: [
				"Press the **microphone** to talk instead of typing. Press **Play** under any answer to hear it read aloud. The sliders button opens voice settings, where you can have every answer read out automatically, change the reading speed, and switch between English, Spanish and French.",
			],
			note: "Each persona has its own voice, and the youngest one reads more slowly. Voice is optional and everything works without it.",
		},
		{
			title: "Games",
			glyph: "shuffle",
			paras: [
				'Ask *"can we play a game"* and a card opens in the chat. There are four: **Word scramble**, where you unscramble a money word; **True or false**, which explains the answer after each round; **Millionaire**, four choices a question; and **Hangman**, one letter at a time. You can ask for a clue, skip a question, or leave at any point — your score is kept either way.',
			],
			note: "Questions are matched to who you are using ASPIRE AI as, so a younger reader and a teenager get different sets. The games are a learning activity for children and teenagers, so the Imani and Azuri personas are not offered them. And a rumor for the explorers: they say whispering *golden goose* to your guide starts something special…",
		},
		{
			title: "Checking if you can join",
			paras: [
				'Ask *"am I eligible?"* and a short check opens. It asks a few questions — age, residency and the like — and tells you where you stand, with the rule behind the answer. Nothing you enter there is an application, and you can close it at any point.',
			],
		},
		{
			title: "Applying",
			paras: [
				'Say *"I want to sign up"* and ASPIRE AI will walk you through the application one question at a time, tell you which documents are needed, and let you upload them. You can stop partway and pick it up again later.',
			],
			note: "A child cannot enrol on their own. If a young person starts an application, ASPIRE AI will explain that kindly and show how to bring in a parent or guardian.",
		},
		{
			title: "What it can and cannot do",
			paras: [],
			can: {
				label: "It can:",
				items: [
					"Answer questions about ASPIRE from published information",
					"Explain how saving, interest and budgeting work",
					"Teach a lesson, set a practice question and play a game",
					"Check eligibility and help fill in an application",
					"Answer in English, Spanish or French",
					"Put you in touch with a person when it cannot help",
				],
			},
			cannot: {
				label: "It cannot:",
				items: [
					"See your account, your balance, or an application you have already sent",
					"Tell you what to do with your money. It will explain how something works and leave the decision to you — for advice about your own situation, speak to the ASPIRE team or a qualified adviser",
					"Make up a figure, a date or a contact detail it does not have",
					"Change anything on your account, or act on your behalf",
				],
			},
			note: "If it does not know something, it will say so and tell you who does. That is a real answer, not a failure.",
		},
		{
			title: "Staying safe",
			paras: [],
			list: [
				"Do not type anything you would not want kept — no passwords, no card or bank numbers. ASPIRE AI never needs them and will never ask.",
				"Personal details are only ever asked for inside an application, and only the ones that application needs.",
				"Conversations are saved so you can come back to them. You can rename or delete any of them from the list on the left.",
				"If you tell ASPIRE AI that you are not safe or that someone is hurting you, it will stop talking about money and make sure a person who can help is told.",
				"ASPIRE AI is a computer program, not a person, and it will always say so if you ask.",
			],
		},
		{
			title: "If something goes wrong",
			paras: [
				"Ask for a person and ASPIRE AI will pass it on, along with the ASPIRE team's contact details. If an answer looks wrong, say so — it will hold to what it has, and give you the official contact for the last word rather than guessing.",
			],
		},
	],
};

const ES: HelpCopy = {
	title: "Cómo usar ASPIRE AI",
	lede: "ASPIRE AI es el asistente del Programa ASPIRE, una iniciativa del Gobierno de San Cristóbal y Nieves. Explica qué es el programa, ayuda a inscribirse y enseña cómo funcionan el ahorro y el dinero.",
	guideRows: {
		skye: {
			audience: "Edades 5–8",
			blurb: "Suave, sin prisa, y llena de asombro.",
		},
		kaleb: {
			audience: "Edades 9–12",
			blurb: "El primo mayor que te dice la verdad.",
		},
		zion: {
			audience: "Edades 13–18",
			blurb: "Directo, con fuentes, y honesto sobre lo que no está decidido.",
		},
		imani: {
			audience: "Madres, padres y tutores",
			blurb: "Respuestas directas sobre el programa, sin hacerte esperar.",
		},
		azuri: {
			audience: "Docentes",
			blurb: "Cifras con fuente y una descripción honesta del material.",
		},
		guest: {
			audience: "General",
			blurb: "Responde antes de saber quién lee. La opción por defecto.",
		},
	},
	sections: [
		{
			title: "Para quién es",
			paras: [
				"Jóvenes de 5 a 18 años, y las madres, padres, tutores y docentes que los acompañan. No necesitas una cuenta para preguntar: iniciar sesión solo hace falta para solicitar, o para guardar tus lecciones entre visitas.",
			],
		},
		{
			title: "Con quién hablas",
			glyph: "person",
			guides: true,
			paras: [
				"Elegir un guía cambia cómo te escribe ASPIRE AI: las palabras que usa, cuánto dura una respuesta y si explica o va al grano. No es solo una etiqueta: la misma pregunta recibe de verdad una respuesta distinta.",
			],
			note: "**Para cambiar:** usa el botón de la persona en la parte de abajo, junto a donde escribes. Puedes cambiarlo cuando quieras, tantas veces como quieras.",
		},
		{
			title: "Explícalo de forma sencilla",
			glyph: "spark",
			paras: [
				"Dos maneras de recibir la misma respuesta con palabras más simples. El botón **Explícalo de forma sencilla** junto al cuadro de texto mantiene cada respuesta nueva corta y clara hasta que lo apagues. O pulsa **Más simple** debajo de cualquier respuesta para que se repita con palabras más fáciles.",
			],
			note: "Cambia las palabras, nunca los hechos: las cifras, las reglas y las fuentes quedan exactamente igual.",
		},
		{
			title: "Escuchar y hablar",
			glyph: "mic",
			paras: [
				"Pulsa el **micrófono** para hablar en lugar de escribir. Pulsa **Escuchar** debajo de cualquier respuesta para oírla en voz alta. El botón de los controles abre los ajustes de voz: lectura automática, velocidad, y el cambio entre inglés, español y francés.",
			],
			note: "Cada guía tiene su propia voz, y la más joven lee más despacio. La voz es opcional y todo funciona sin ella.",
		},
		{
			title: "Juegos",
			glyph: "shuffle",
			paras: [
				"Pide *«¿jugamos a algo?»* y se abre una tarjeta en el chat. Hay cuatro: **Palabras revueltas**, donde ordenas una palabra de dinero; **Verdadero o falso**, que explica la respuesta en cada ronda; **Millonario**, cuatro opciones por pregunta; y **Ahorcado**, letra a letra. Puedes pedir una pista, saltar una pregunta o salir cuando quieras: tu puntuación se guarda igual.",
			],
			note: "Las preguntas se ajustan a quién eres al usar ASPIRE AI: un lector joven y un adolescente reciben series distintas. Los juegos son una actividad para niños y adolescentes, así que Imani y Azuri no los reciben. Y un rumor para quienes exploran: dicen que susurrar *la gansa dorada* a tu guía hace que empiece algo especial…",
		},
		{
			title: "Comprobar si puedes entrar",
			paras: [
				"Pregunta *«¿soy elegible?»* y se abre una comprobación corta. Hace unas pocas preguntas —edad, residencia y similares— y te dice dónde estás, con la regla detrás de la respuesta. Nada de lo que escribas ahí es una solicitud, y puedes cerrarla en cualquier momento.",
			],
		},
		{
			title: "Solicitar",
			paras: [
				"Di *«quiero inscribirme»* y ASPIRE AI te guiará por la solicitud pregunta a pregunta, te dirá qué documentos hacen falta y te dejará subirlos. Puedes parar a medias y retomarla más tarde.",
			],
			note: "Un menor no puede inscribirse solo. Si un joven empieza una solicitud, ASPIRE AI se lo explicará con amabilidad y le mostrará cómo traer a su madre, padre o tutor.",
		},
		{
			title: "Qué puede y qué no puede hacer",
			paras: [],
			can: {
				label: "Puede:",
				items: [
					"Responder preguntas sobre ASPIRE con información publicada",
					"Explicar cómo funcionan el ahorro, el interés y el presupuesto",
					"Dar una lección, poner una pregunta de práctica y jugar un juego",
					"Comprobar la elegibilidad y ayudar a rellenar una solicitud",
					"Responder en inglés, español o francés",
					"Ponerte en contacto con una persona cuando no puede ayudar",
				],
			},
			cannot: {
				label: "No puede:",
				items: [
					"Ver tu cuenta, tu saldo, ni una solicitud ya enviada",
					"Decirte qué hacer con tu dinero. Te explicará cómo funciona algo y la decisión queda contigo; para consejos sobre tu situación, habla con el equipo de ASPIRE o con un asesor calificado",
					"Inventar una cifra, una fecha o un contacto que no tiene",
					"Cambiar nada en tu cuenta, ni actuar en tu nombre",
				],
			},
			note: "Si no sabe algo, lo dirá y te dirá quién sí lo sabe. Eso es una respuesta de verdad, no un fallo.",
		},
		{
			title: "Tu seguridad",
			paras: [],
			list: [
				"No escribas nada que no quieras que quede guardado: ni contraseñas, ni números de tarjeta o de banco. ASPIRE AI nunca los necesita y nunca los pedirá.",
				"Los datos personales solo se piden dentro de una solicitud, y solo los que esa solicitud necesita.",
				"Las conversaciones se guardan para que puedas volver a ellas. Puedes renombrarlas o borrarlas desde la lista de la izquierda.",
				"Si le dices a ASPIRE AI que no estás a salvo o que alguien te hace daño, dejará de hablar de dinero y se asegurará de avisar a una persona que pueda ayudar.",
				"ASPIRE AI es un programa de computadora, no una persona, y siempre lo dirá si se lo preguntas.",
			],
		},
		{
			title: "Si algo sale mal",
			paras: [
				"Pide hablar con una persona y ASPIRE AI lo pasará, junto con los contactos del equipo de ASPIRE. Si una respuesta parece incorrecta, dilo: se mantendrá en lo que tiene y te dará el contacto oficial para la última palabra, en lugar de adivinar.",
			],
		},
	],
};

const FR: HelpCopy = {
	title: "Comment utiliser ASPIRE AI",
	lede: "ASPIRE AI est l'assistant du Programme ASPIRE, une initiative du Gouvernement de Saint-Christophe-et-Niévès. Il explique le programme, aide à s'y inscrire et enseigne comment fonctionnent l'épargne et l'argent.",
	guideRows: {
		skye: {
			audience: "5–8 ans",
			blurb: "Douce, sans hâte, pleine d'émerveillement.",
		},
		kaleb: {
			audience: "9–12 ans",
			blurb: "Le grand cousin qui te dit la vérité.",
		},
		zion: {
			audience: "13–18 ans",
			blurb: "Direct, sourcé, honnête sur ce qui n'est pas décidé.",
		},
		imani: {
			audience: "Parents et tuteurs",
			blurb: "Des réponses directes sur le programme, sans file d'attente.",
		},
		azuri: {
			audience: "Enseignants",
			blurb: "Des chiffres sourcés et une description honnête du matériel.",
		},
		guest: {
			audience: "Général",
			blurb: "Répond avant de savoir qui lit. Le choix par défaut.",
		},
	},
	sections: [
		{
			title: "Pour qui",
			paras: [
				"Les jeunes de 5 à 18 ans, et les parents, tuteurs et enseignants qui les accompagnent. Pas besoin de compte pour poser une question — se connecter ne sert qu'à faire une demande, ou à garder tes leçons d'une visite à l'autre.",
			],
		},
		{
			title: "À qui tu parles",
			glyph: "person",
			guides: true,
			paras: [
				"Choisir un guide change la façon dont ASPIRE AI t'écrit : les mots choisis, la longueur des réponses, et s'il explique ou va droit au but. Ce n'est pas une étiquette — la même question reçoit vraiment une réponse différente.",
			],
			note: "**Pour changer :** utilise le bouton de la personne en bas de l'écran, à côté de la zone de saisie. Tu peux changer à tout moment, aussi souvent que tu veux.",
		},
		{
			title: "Explique-le simplement",
			glyph: "spark",
			paras: [
				"Deux façons d'obtenir la même réponse en plus simple. Le bouton **Explique-le simplement** à côté de la zone de texte garde chaque nouvelle réponse courte et claire jusqu'à ce que tu le désactives. Ou appuie sur **Plus simple** sous n'importe quelle réponse pour qu'elle soit redite avec des mots plus faciles.",
			],
			note: "Cela change les mots, jamais les faits — les chiffres, les règles et les sources restent exactement les mêmes.",
		},
		{
			title: "Écouter et parler",
			glyph: "mic",
			paras: [
				"Appuie sur le **micro** pour parler au lieu d'écrire. Appuie sur **Écouter** sous une réponse pour l'entendre à voix haute. Le bouton des réglages ouvre les paramètres de voix : lecture automatique, vitesse, et le choix entre anglais, espagnol et français.",
			],
			note: "Chaque guide a sa propre voix, et la plus jeune lit plus lentement. La voix est optionnelle et tout fonctionne sans elle.",
		},
		{
			title: "Jeux",
			glyph: "shuffle",
			paras: [
				"Demande *« on joue à un jeu ? »* et une carte s'ouvre dans la discussion. Il y en a quatre : **Mots mélangés**, où tu remets une mot d'argent en ordre ; **Vrai ou faux**, qui explique la réponse à chaque tour ; **Millionnaire**, quatre choix par question ; et **Le pendu**, lettre par lettre. Tu peux demander un indice, passer une question ou partir quand tu veux — ton score est gardé quand même.",
			],
			note: "Les questions s'adaptent à qui tu es dans ASPIRE AI : un jeune lecteur et un adolescent reçoivent des séries différentes. Les jeux sont une activité pour les enfants et les adolescents, donc Imani et Azuri ne les reçoivent pas. Et une rumeur pour les curieux : on dit que chuchoter *l'oie dorée* à ton guide déclenche quelque chose de spécial…",
		},
		{
			title: "Vérifier si tu peux entrer",
			paras: [
				"Demande *« suis-je éligible ? »* et une courte vérification s'ouvre. Elle pose quelques questions — âge, résidence, etc. — et te dit où tu en es, avec la règle derrière la réponse. Rien de ce que tu y saisis n'est une demande, et tu peux fermer à tout moment.",
			],
		},
		{
			title: "Faire une demande",
			paras: [
				"Dis *« je veux m'inscrire »* et ASPIRE AI te guidera dans la demande question par question, te dira quels documents il faut et te laissera les téléverser. Tu peux t'arrêter en cours et reprendre plus tard.",
			],
			note: "Un enfant ne peut pas s'inscrire seul. Si un jeune commence une demande, ASPIRE AI l'expliquera gentiment et montrera comment faire venir un parent ou un tuteur.",
		},
		{
			title: "Ce qu'il peut et ne peut pas faire",
			paras: [],
			can: {
				label: "Il peut :",
				items: [
					"Répondre aux questions sur ASPIRE à partir d'informations publiées",
					"Expliquer comment fonctionnent l'épargne, l'intérêt et le budget",
					"Donner une leçon, poser une question d'entraînement et jouer à un jeu",
					"Vérifier l'éligibilité et aider à remplir une demande",
					"Répondre en anglais, en espagnol ou en français",
					"Te mettre en contact avec une personne quand il ne peut pas aider",
				],
			},
			cannot: {
				label: "Il ne peut pas :",
				items: [
					"Voir ton compte, ton solde, ou une demande déjà envoyée",
					"Te dire quoi faire de ton argent. Il expliquera comment cela fonctionne et la décision te revient ; pour des conseils sur ta situation, parle à l'équipe ASPIRE ou à un conseiller qualifié",
					"Inventer un chiffre, une date ou un contact qu'il n'a pas",
					"Modifier quoi que ce soit sur ton compte, ou agir à ta place",
				],
			},
			note: "S'il ne sait pas, il le dira et te dira qui sait. C'est une vraie réponse, pas un échec.",
		},
		{
			title: "Ta sécurité",
			paras: [],
			list: [
				"N'écris rien que tu ne voudrais pas voir gardé — ni mots de passe, ni numéros de carte ou de banque. ASPIRE AI n'en a jamais besoin et ne les demandera jamais.",
				"Les données personnelles ne sont demandées que dans une demande, et seulement celles dont elle a besoin.",
				"Les conversations sont gardées pour que tu puisses y revenir. Tu peux les renommer ou les supprimer depuis la liste à gauche.",
				"Si tu dis à ASPIRE AI que tu n'es pas en sécurité ou que quelqu'un te fait du mal, il arrêtera de parler d'argent et fera en sorte qu'une personne qui peut aider soit prévenue.",
				"ASPIRE AI est un programme informatique, pas une personne, et il le dira toujours si tu le demandes.",
			],
		},
		{
			title: "Si quelque chose ne va pas",
			paras: [
				"Demande une personne et ASPIRE AI transmettra, avec les coordonnées de l'équipe ASPIRE. Si une réponse semble fausse, dis-le : il s'en tiendra à ce qu'il a et te donnera le contact officiel pour le dernier mot, plutôt que de deviner.",
			],
		},
	],
};

const COPY: Record<Locale, HelpCopy> = { en: EN, es: ES, fr: FR };

export function helpCopy(locale: Locale): HelpCopy {
	return COPY[locale] ?? EN;
}
