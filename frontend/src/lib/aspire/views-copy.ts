/** The three section views' copy, per locale. One file, translator-friendly. */

import type { Locale } from "./i18n";

export interface GalleryCopy {
	title: string;
	lede: string;
	comingSoon: string;
	photosTitle: string;
	photosBody: string;
	videosTitle: string;
	videosBody: string;
}

export interface ViewsCopy {
	backToChat: string;
	journey: {
		title: string;
		lede: string;
		accountTitle: string;
		accountBody: string;
		signIn: string;
		learnTitle: string;
		stages: string[];
		shelfTitle: string;
		shelfLede: string;
		tinTitle: string;
		tinLede: string;
		tinNext: string;
	};
	parents: {
		title: string;
		lede: string;
		grantTitle: string;
		grantBody: string;
		grantItems: string[];
		regTitle: string;
		regBody1: string;
		regBody2: string;
		needLabel: string;
		needItems: string[];
		ctaTitle: string;
		ctaBody: string;
		ctaButton: string;
	};
	gallery: GalleryCopy;
	educators: {
		title: string;
		lede: string;
		currTitle: string;
		currBody: string;
		topics: string[];
		trainTitle: string;
		trainBody: string;
		interTitle: string;
		interBody: string;
	};
}

const EN: ViewsCopy = {
	backToChat: "Back to chat",
	journey: {
		title: "Your financial journey",
		lede: "Track your progress as you master new money skills, earn badges, and build your future in St. Kitts and Nevis.",
		accountTitle: "Your progress lives with your account",
		accountBody: "Sign in and your badges, lessons and coins follow you here.",
		signIn: "Sign in",
		learnTitle: "What you will learn",
		stages: ["Basics", "Saving", "Budgeting", "Investing", "Business"],
		shelfTitle: "Your story artifacts",
		shelfLede: "Earned by playing a story all the way to its ending.",
		tinTitle: "The Tin",
		tinLede:
			"Coins land here when you finish stories, complete games and sign pledges. It only ever fills.",
		tinNext: "{n} to the next milestone",
	},
	parents: {
		title: "For parents & guardians",
		lede: "Secure your child's financial future with the ASPIRE Programme.",
		grantTitle: "The EC$1,000 grant",
		grantBody:
			"Every eligible child (ages 5–18) receives an EC$1,000 contribution from the Government of St. Kitts and Nevis:",
		grantItems: [
			"EC$500 in a savings account at the St. Kitts-Nevis-Anguilla National Bank",
			"EC$500 invested in shares of local government-owned entities",
		],
		regTitle: "How to register",
		regBody1: "Register online at",
		regBody2:
			", or in person at The Cable Office on Cayon Street in Basseterre — walk-in support is available Monday to Friday, 9:00 AM to 3:00 PM.",
		needLabel: "What you'll need",
		needItems: [
			"Parent or guardian valid ID",
			"Child's SKN birth certificate or passport",
			"Recent proof of address (within 3 months)",
		],
		ctaTitle: "Ready to register your child?",
		ctaBody: "Help them build wealth and learn financial literacy early.",
		ctaButton: "Register your child",
	},
	gallery: {
		title: "Gallery",
		lede: "Moments from the ASPIRE Programme, across St. Kitts and Nevis.",
		comingSoon: "Coming soon",
		photosTitle: "Pictures",
		photosBody:
			"Photographs from ASPIRE Days, school visits and registration drives across the Federation.",
		videosTitle: "Video",
		videosBody: "Highlights, stories and moments from the programme, on film.",
	},
	educators: {
		title: "For educators",
		lede: "Empower the next generation with essential financial literacy.",
		currTitle: "The ASPIRE AI financial curriculum",
		currBody:
			"Educators are at the heart of ASPIRE's financial literacy programme. Developed by the ASPIRE AI team in collaboration with the Eastern Caribbean Central Bank, the curriculum introduces students to the ideas that will shape their financial futures — and gives every learner a guide who meets them at their own age.",
		topics: [
			"Budgeting",
			"Saving",
			"Investing",
			"Debt management",
			"Entrepreneurship",
		],
		trainTitle: "Educator training",
		trainBody:
			"The ASPIRE Programme hosts specialised educator training sessions to equip teachers with the knowledge and tools to teach financial literacy confidently in the classroom.",
		interTitle: "Interactive learning",
		interBody:
			"Our AI assistant and gamified learning paths reinforce classroom lessons, letting students play, explore and earn rewards while mastering the EC dollar.",
	},
};

const ES: ViewsCopy = {
	backToChat: "Volver al chat",
	journey: {
		title: "Tu camino financiero",
		lede: "Sigue tu progreso mientras dominas nuevas habilidades con el dinero, ganas insignias y construyes tu futuro en San Cristóbal y Nieves.",
		accountTitle: "Tu progreso vive con tu cuenta",
		accountBody:
			"Inicia sesión y tus insignias, lecciones y monedas te siguen hasta aquí.",
		signIn: "Iniciar sesión",
		learnTitle: "Lo que vas a aprender",
		stages: ["Fundamentos", "Ahorro", "Presupuesto", "Inversión", "Negocios"],
		shelfTitle: "Tus artefactos de cuentos",
		shelfLede: "Se ganan jugando un cuento hasta su final.",
		tinTitle: "La Alcancía",
		tinLede:
			"Aquí caen monedas cuando terminas cuentos, completas juegos y firmas compromisos. Solo se llena.",
		tinNext: "{n} para el siguiente hito",
	},
	parents: {
		title: "Para madres, padres y tutores",
		lede: "Asegura el futuro financiero de tu hijo o hija con el Programa ASPIRE.",
		grantTitle: "El aporte de EC$1,000",
		grantBody:
			"Cada menor elegible (de 5 a 18 años) recibe un aporte de EC$1,000 del Gobierno de San Cristóbal y Nieves:",
		grantItems: [
			"EC$500 en una cuenta de ahorros en el St. Kitts-Nevis-Anguilla National Bank",
			"EC$500 invertidos en acciones de entidades públicas locales",
		],
		regTitle: "Cómo registrarse",
		regBody1: "Regístrate en línea en",
		regBody2:
			", o en persona en The Cable Office, en Cayon Street, Basseterre — con atención sin cita de lunes a viernes, de 9:00 AM a 3:00 PM.",
		needLabel: "Lo que necesitarás",
		needItems: [
			"Identificación vigente de la madre, el padre o el tutor",
			"Certificado de nacimiento de SKN o pasaporte del menor",
			"Comprobante de domicilio reciente (de los últimos 3 meses)",
		],
		ctaTitle: "¿Todo listo para registrar a tu hijo o hija?",
		ctaBody:
			"Ayúdales a construir patrimonio y aprender finanzas desde temprano.",
		ctaButton: "Registrar a tu hijo o hija",
	},
	gallery: {
		title: "Galería",
		lede: "Momentos del Programa ASPIRE, por todo San Cristóbal y Nieves.",
		comingSoon: "Próximamente",
		photosTitle: "Fotos",
		photosBody:
			"Fotografías de los Días ASPIRE, visitas escolares y jornadas de registro por toda la Federación.",
		videosTitle: "Vídeo",
		videosBody: "Momentos destacados e historias del programa, en vídeo.",
	},
	educators: {
		title: "Para docentes",
		lede: "Fortalece a la próxima generación con educación financiera esencial.",
		currTitle: "El plan de estudios financiero de ASPIRE AI",
		currBody:
			"El personal docente está en el corazón del programa de educación financiera de ASPIRE. Desarrollado por el equipo de ASPIRE AI en colaboración con el Banco Central del Caribe Oriental, el plan introduce a los estudiantes a las ideas que formarán su futuro financiero — y le da a cada estudiante un guía que lo acompaña a su propia edad.",
		topics: [
			"Presupuesto",
			"Ahorro",
			"Inversión",
			"Manejo de deudas",
			"Emprendimiento",
		],
		trainTitle: "Formación docente",
		trainBody:
			"El Programa ASPIRE organiza sesiones de formación especializadas para dar al profesorado el conocimiento y las herramientas para enseñar educación financiera con confianza en el aula.",
		interTitle: "Aprendizaje interactivo",
		interBody:
			"Nuestro asistente de IA y las rutas de aprendizaje gamificadas refuerzan las lecciones del aula: los estudiantes juegan, exploran y ganan recompensas mientras dominan el dólar del Caribe Oriental.",
	},
};

const FR: ViewsCopy = {
	backToChat: "Retour au chat",
	journey: {
		title: "Ton parcours financier",
		lede: "Suis tes progrès pendant que tu maîtrises de nouvelles compétences, gagnes des badges et construis ton avenir à Saint-Christophe-et-Niévès.",
		accountTitle: "Tes progrès vivent avec ton compte",
		accountBody: "Connecte-toi et tes badges, leçons et pièces te suivent ici.",
		signIn: "Se connecter",
		learnTitle: "Ce que tu vas apprendre",
		stages: ["Bases", "Épargne", "Budget", "Investissement", "Entreprise"],
		shelfTitle: "Tes artefacts d'histoires",
		shelfLede: "Gagnés en jouant une histoire jusqu'à sa fin.",
		tinTitle: "La Tirelire",
		tinLede:
			"Les pièces tombent ici quand tu finis des histoires, termines des jeux et signes des engagements. Elle ne fait que se remplir.",
		tinNext: "{n} avant le prochain palier",
	},
	parents: {
		title: "Pour les parents et tuteurs",
		lede: "Assurez l'avenir financier de votre enfant avec le Programme ASPIRE.",
		grantTitle: "L'apport de 1 000 EC$",
		grantBody:
			"Chaque enfant éligible (de 5 à 18 ans) reçoit un apport de 1 000 EC$ du Gouvernement de Saint-Christophe-et-Niévès :",
		grantItems: [
			"500 EC$ sur un compte d'épargne à la St. Kitts-Nevis-Anguilla National Bank",
			"500 EC$ investis en parts d'entités publiques locales",
		],
		regTitle: "Comment s'inscrire",
		regBody1: "Inscrivez-vous en ligne sur",
		regBody2:
			", ou en personne au Cable Office, Cayon Street, Basseterre — accueil sans rendez-vous du lundi au vendredi, de 9 h à 15 h.",
		needLabel: "Ce qu'il vous faudra",
		needItems: [
			"Pièce d'identité valide du parent ou tuteur",
			"Acte de naissance SKN ou passeport de l'enfant",
			"Justificatif de domicile récent (moins de 3 mois)",
		],
		ctaTitle: "Prêt à inscrire votre enfant ?",
		ctaBody: "Aidez-le à bâtir un patrimoine et à apprendre les finances tôt.",
		ctaButton: "Inscrire votre enfant",
	},
	gallery: {
		title: "Galerie",
		lede: "Des moments du Programme ASPIRE, à travers Saint-Christophe-et-Niévès.",
		comingSoon: "Bientôt disponible",
		photosTitle: "Photos",
		photosBody:
			"Des photos des Journées ASPIRE, des visites d'écoles et des campagnes d'inscription dans toute la Fédération.",
		videosTitle: "Vidéo",
		videosBody: "Les temps forts et les histoires du programme, en vidéo.",
	},
	educators: {
		title: "Pour les enseignants",
		lede: "Donnez à la prochaine génération une éducation financière essentielle.",
		currTitle: "Le programme financier d'ASPIRE AI",
		currBody:
			"Les enseignants sont au cœur du programme d'éducation financière d'ASPIRE. Élaboré par l'équipe ASPIRE AI en collaboration avec la Banque centrale des Caraïbes orientales, le programme initie les élèves aux idées qui façonneront leur avenir financier — et donne à chaque élève un guide qui le rejoint à son âge.",
		topics: [
			"Budget",
			"Épargne",
			"Investissement",
			"Gestion des dettes",
			"Entrepreneuriat",
		],
		trainTitle: "Formation des enseignants",
		trainBody:
			"Le Programme ASPIRE organise des formations spécialisées pour donner aux enseignants les connaissances et les outils pour enseigner l'éducation financière avec assurance en classe.",
		interTitle: "Apprentissage interactif",
		interBody:
			"Notre assistant IA et nos parcours ludiques renforcent les leçons de classe : les élèves jouent, explorent et gagnent des récompenses tout en maîtrisant le dollar des Caraïbes orientales.",
	},
};

const COPY: Record<Locale, ViewsCopy> = { en: EN, es: ES, fr: FR };

export function viewsCopy(locale: Locale): ViewsCopy {
	return COPY[locale] ?? EN;
}
