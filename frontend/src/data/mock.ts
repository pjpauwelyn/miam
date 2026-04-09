export interface Recipe {
  id: string;
  title: string;
  cuisine: string[];
  dietary: string[];
  time: number;
  difficulty: number;
  matchScore: number;
  description: string;
  servings: number;
  ingredients: Ingredient[];
  steps: Step[];
  nutrition: Nutrition;
  flavourTags: string[];
  textureTags: string[];
}

export interface Ingredient {
  name: string;
  amount: string;
  unit: string;
  substitution?: string;
}

export interface Step {
  number: number;
  instruction: string;
  techniqueTags: string[];
}

export interface Nutrition {
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  fibre: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  recipeIds?: string[];
}

export const recipes: Recipe[] = [
  {
    id: 'miso-aubergine',
    title: 'Miso-Glazed Aubergine with Sesame Rice',
    cuisine: ['Japanese'],
    dietary: ['Vegan', 'Dairy-Free'],
    time: 35,
    difficulty: 2,
    matchScore: 94,
    description: 'Tender aubergine halves caramelised under a sweet-savoury white miso glaze, served on fluffy short-grain rice flecked with toasted sesame and spring onion. A weeknight staple that feels special.',
    servings: 2,
    ingredients: [
      { name: 'Aubergine', amount: '2', unit: 'medium', substitution: 'Courgette halves' },
      { name: 'White miso paste', amount: '3', unit: 'tbsp' },
      { name: 'Mirin', amount: '2', unit: 'tbsp' },
      { name: 'Rice vinegar', amount: '1', unit: 'tbsp' },
      { name: 'Caster sugar', amount: '1', unit: 'tbsp' },
      { name: 'Sesame oil', amount: '2', unit: 'tsp' },
      { name: 'Short-grain rice', amount: '200', unit: 'g' },
      { name: 'Toasted sesame seeds', amount: '2', unit: 'tbsp' },
      { name: 'Spring onions', amount: '3', unit: 'stalks' },
      { name: 'Vegetable oil', amount: '1', unit: 'tbsp' },
      { name: 'Chilli flakes', amount: '1', unit: 'pinch' },
    ],
    steps: [
      { number: 1, instruction: 'Rinse the rice under cold water until it runs clear. Cook in salted water for 12 minutes, then let it steam with the lid on for 10 minutes.', techniqueTags: ['Boiling', 'Steaming'] },
      { number: 2, instruction: 'Halve the aubergines lengthways and score the flesh in a cross-hatch pattern. Brush with vegetable oil and season.', techniqueTags: ['Knife skills'] },
      { number: 3, instruction: 'Place aubergines cut-side down in a hot pan and cook for 5 minutes until golden. Flip and cook 3 more minutes.', techniqueTags: ['Pan-frying'] },
      { number: 4, instruction: 'Whisk together the miso, mirin, rice vinegar, sugar and sesame oil until smooth.', techniqueTags: ['Emulsifying'] },
      { number: 5, instruction: 'Brush the miso glaze generously over the aubergine halves. Grill under a high heat for 3–4 minutes until bubbling and caramelised.', techniqueTags: ['Grilling', 'Glazing'] },
      { number: 6, instruction: 'Fold sesame seeds and sliced spring onions through the rice. Serve topped with the glazed aubergine and a scatter of chilli flakes.', techniqueTags: ['Plating'] },
    ],
    nutrition: { calories: 420, protein: 10, carbs: 68, fat: 12, fibre: 8 },
    flavourTags: ['Umami', 'Sweet-savoury', 'Smoky'],
    textureTags: ['Creamy', 'Nutty', 'Caramelised'],
  },
  {
    id: 'pasta-norma',
    title: 'Pasta alla Norma',
    cuisine: ['Italian', 'Sicilian'],
    dietary: ['Vegetarian'],
    time: 40,
    difficulty: 2,
    matchScore: 87,
    description: 'Sicily\'s beloved pasta: rigatoni tossed in a rich tomato sauce with golden-fried aubergine cubes, finished with torn basil and a flurry of ricotta salata. Rustic, bold, and deeply satisfying.',
    servings: 4,
    ingredients: [
      { name: 'Rigatoni', amount: '400', unit: 'g' },
      { name: 'Aubergine', amount: '2', unit: 'large' },
      { name: 'Tinned plum tomatoes', amount: '400', unit: 'g' },
      { name: 'Garlic', amount: '3', unit: 'cloves' },
      { name: 'Fresh basil', amount: '1', unit: 'bunch' },
      { name: 'Ricotta salata', amount: '80', unit: 'g', substitution: 'Pecorino Romano' },
      { name: 'Extra-virgin olive oil', amount: '4', unit: 'tbsp' },
      { name: 'Dried chilli flakes', amount: '½', unit: 'tsp' },
      { name: 'Sea salt', amount: '', unit: 'to taste' },
    ],
    steps: [
      { number: 1, instruction: 'Cut the aubergine into 2cm cubes, salt generously, and leave in a colander for 20 minutes. Pat dry.', techniqueTags: ['Salting', 'Degorging'] },
      { number: 2, instruction: 'Fry the aubergine cubes in batches in hot olive oil until deep golden. Drain on kitchen paper.', techniqueTags: ['Deep-frying'] },
      { number: 3, instruction: 'In the same pan, soften garlic and chilli flakes in a little oil. Add the tomatoes and simmer for 15 minutes, breaking them down with a spoon.', techniqueTags: ['Sautéing', 'Simmering'] },
      { number: 4, instruction: 'Cook the rigatoni in well-salted boiling water until al dente. Reserve a cup of pasta water before draining.', techniqueTags: ['Boiling'] },
      { number: 5, instruction: 'Toss the pasta and fried aubergine through the sauce, adding splashes of pasta water to emulsify.', techniqueTags: ['Tossing', 'Emulsifying'] },
      { number: 6, instruction: 'Serve with torn basil and generous gratings of ricotta salata.', techniqueTags: ['Plating'] },
    ],
    nutrition: { calories: 520, protein: 16, carbs: 72, fat: 18, fibre: 6 },
    flavourTags: ['Tangy', 'Herbaceous', 'Savoury'],
    textureTags: ['Al dente', 'Crispy', 'Saucy'],
  },
  {
    id: 'thai-green-curry',
    title: 'Thai Green Curry with Tofu',
    cuisine: ['Thai'],
    dietary: ['Vegan', 'Gluten-Free'],
    time: 30,
    difficulty: 2,
    matchScore: 91,
    description: 'A fragrant, creamy green curry loaded with crispy tofu, Thai aubergine, and fresh vegetables. Coconut milk rounds out the bright chilli-lemongrass paste. Serve over jasmine rice for a complete meal.',
    servings: 3,
    ingredients: [
      { name: 'Firm tofu', amount: '300', unit: 'g', substitution: 'Chickpeas (drained)' },
      { name: 'Green curry paste', amount: '3', unit: 'tbsp' },
      { name: 'Coconut milk', amount: '400', unit: 'ml' },
      { name: 'Thai aubergine', amount: '4', unit: 'pieces', substitution: 'Regular aubergine cubes' },
      { name: 'Bamboo shoots', amount: '100', unit: 'g' },
      { name: 'Thai basil', amount: '1', unit: 'handful' },
      { name: 'Kaffir lime leaves', amount: '4', unit: 'leaves' },
      { name: 'Palm sugar', amount: '1', unit: 'tsp' },
      { name: 'Soy sauce', amount: '1', unit: 'tbsp' },
      { name: 'Vegetable oil', amount: '1', unit: 'tbsp' },
      { name: 'Jasmine rice', amount: '250', unit: 'g' },
    ],
    steps: [
      { number: 1, instruction: 'Press the tofu, cut into cubes and pan-fry in a little oil until golden on all sides. Set aside.', techniqueTags: ['Pressing', 'Pan-frying'] },
      { number: 2, instruction: 'In a wok or deep pan, heat a tablespoon of the thick coconut cream and fry the curry paste for 2 minutes until fragrant.', techniqueTags: ['Blooming'] },
      { number: 3, instruction: 'Pour in the remaining coconut milk, add the lime leaves, and bring to a gentle simmer.', techniqueTags: ['Simmering'] },
      { number: 4, instruction: 'Add the aubergine and bamboo shoots. Cook for 8 minutes until tender.', techniqueTags: ['Braising'] },
      { number: 5, instruction: 'Season with palm sugar and soy sauce. Return the tofu to the pan and warm through.', techniqueTags: ['Seasoning'] },
      { number: 6, instruction: 'Finish with torn Thai basil. Serve ladled over steamed jasmine rice.', techniqueTags: ['Plating'] },
    ],
    nutrition: { calories: 480, protein: 18, carbs: 45, fat: 26, fibre: 5 },
    flavourTags: ['Aromatic', 'Spicy', 'Creamy'],
    textureTags: ['Crispy', 'Silky', 'Tender'],
  },
  {
    id: 'mushroom-risotto',
    title: 'Mushroom Risotto with Truffle Oil',
    cuisine: ['Italian'],
    dietary: ['Vegetarian', 'Gluten-Free'],
    time: 45,
    difficulty: 3,
    matchScore: 82,
    description: 'A luxuriously creamy risotto built on a base of mixed wild mushrooms and arborio rice, finished with a drizzle of truffle oil and shaved Parmigiano Reggiano. Patient stirring rewards you with pure velvet.',
    servings: 2,
    ingredients: [
      { name: 'Arborio rice', amount: '200', unit: 'g' },
      { name: 'Mixed mushrooms', amount: '300', unit: 'g', substitution: 'Button mushrooms' },
      { name: 'Vegetable stock', amount: '800', unit: 'ml' },
      { name: 'Shallot', amount: '1', unit: 'large' },
      { name: 'Dry white wine', amount: '100', unit: 'ml' },
      { name: 'Parmigiano Reggiano', amount: '60', unit: 'g' },
      { name: 'Unsalted butter', amount: '30', unit: 'g' },
      { name: 'Truffle oil', amount: '1', unit: 'tsp' },
      { name: 'Fresh thyme', amount: '3', unit: 'sprigs' },
      { name: 'Olive oil', amount: '2', unit: 'tbsp' },
    ],
    steps: [
      { number: 1, instruction: 'Warm the vegetable stock in a saucepan and keep it at a gentle simmer.', techniqueTags: ['Mise en place'] },
      { number: 2, instruction: 'Sauté the mushrooms in olive oil over high heat until golden. Season and add the thyme. Set aside half for garnish.', techniqueTags: ['Sautéing'] },
      { number: 3, instruction: 'In the same pan, sweat the finely diced shallot in butter until translucent. Add the rice and toast for 2 minutes.', techniqueTags: ['Sweating', 'Toasting'] },
      { number: 4, instruction: 'Pour in the wine and stir until absorbed. Begin adding the stock one ladle at a time, stirring frequently and waiting for each addition to be absorbed.', techniqueTags: ['Deglazing', 'Risotto technique'] },
      { number: 5, instruction: 'After about 18 minutes, when the rice is creamy but still has a slight bite, fold in the sautéed mushrooms, grated Parmigiano, and remaining butter (mantecatura).', techniqueTags: ['Mantecatura'] },
      { number: 6, instruction: 'Serve immediately, topped with reserved mushrooms, a drizzle of truffle oil, and shaved Parmigiano.', techniqueTags: ['Plating'] },
    ],
    nutrition: { calories: 580, protein: 20, carbs: 65, fat: 24, fibre: 4 },
    flavourTags: ['Earthy', 'Rich', 'Truffle'],
    textureTags: ['Creamy', 'Velvety', 'Al dente'],
  },
];

export const chatMessages: ChatMessage[] = [
  {
    id: 'msg-1',
    role: 'user',
    content: 'I feel like something Japanese tonight, maybe with aubergine?',
  },
  {
    id: 'msg-2',
    role: 'assistant',
    content: 'Great choice! Here\'s a Japanese dish that showcases aubergine beautifully — the miso glaze gives it an incredible caramelised finish.',
    recipeIds: ['miso-aubergine'],
  },
  {
    id: 'msg-3',
    role: 'user',
    content: 'That looks perfect! What about something Italian instead?',
  },
  {
    id: 'msg-4',
    role: 'assistant',
    content: 'For Italian, I\'d recommend these two — a classic Sicilian pasta and a luxurious risotto:',
    recipeIds: ['pasta-norma', 'mushroom-risotto'],
  },
];

export const suggestionChips = [
  'Quick dinner',
  'Something Japanese',
  'Vegan comfort food',
  'Under 30 min',
  'Date night',
  'Budget-friendly',
];

export const onboardingDietaryOptions = [
  'Omnivore',
  'Vegetarian',
  'Vegan',
  'Pescatarian',
  'Flexitarian',
  'Keto',
  'Paleo',
];

export const onboardingRestrictions = {
  Allergies: ['Nuts', 'Gluten', 'Dairy', 'Soy', 'Shellfish', 'Eggs'],
  Preferences: ['No red meat', 'No pork', 'No alcohol in cooking', 'Low sodium', 'Low sugar'],
};

export const discoverCategories = [
  'Japanese', 'Italian', 'Thai', 'Mexican', 'Indian', 'French', 'Korean', 'Mediterranean',
];

// ---------------------------------------------------------------------------
// User-created recipes
// ---------------------------------------------------------------------------

export interface UserRecipe extends Recipe {
  isPublic: boolean;
  createdBy: string;
  source: 'manual' | 'ai-generated';
  createdAt: string; // ISO 8601
  notes?: string;
}

export const userRecipes: UserRecipe[] = [
  {
    id: 'user-harissa-cauliflower',
    title: 'Harissa-Roasted Cauliflower with Tahini',
    cuisine: ['Middle Eastern'],
    dietary: ['Vegan', 'Gluten-Free'],
    time: 40,
    difficulty: 1,
    matchScore: 0,
    description: 'Whole cauliflower florets roasted with harissa paste until charred at the edges, drizzled with lemon-tahini sauce and scattered with pomegranate seeds and fresh mint.',
    servings: 2,
    ingredients: [
      { name: 'Cauliflower', amount: '1', unit: 'large head' },
      { name: 'Harissa paste', amount: '3', unit: 'tbsp' },
      { name: 'Olive oil', amount: '2', unit: 'tbsp' },
      { name: 'Tahini', amount: '3', unit: 'tbsp' },
      { name: 'Lemon juice', amount: '2', unit: 'tbsp' },
      { name: 'Pomegranate seeds', amount: '3', unit: 'tbsp' },
      { name: 'Fresh mint', amount: '1', unit: 'handful' },
      { name: 'Garlic', amount: '1', unit: 'clove' },
    ],
    steps: [
      { number: 1, instruction: 'Preheat the oven to 220°C. Cut the cauliflower into large florets.', techniqueTags: ['Prep'] },
      { number: 2, instruction: 'Toss florets with harissa paste and olive oil. Spread on a baking tray.', techniqueTags: ['Marinating'] },
      { number: 3, instruction: 'Roast for 30 minutes until charred at the edges and tender.', techniqueTags: ['Roasting'] },
      { number: 4, instruction: 'Whisk tahini with lemon juice, crushed garlic, and a splash of water until smooth.', techniqueTags: ['Emulsifying'] },
      { number: 5, instruction: 'Drizzle tahini sauce over the cauliflower. Scatter with pomegranate seeds and torn mint leaves.', techniqueTags: ['Plating'] },
    ],
    nutrition: { calories: 320, protein: 12, carbs: 28, fat: 20, fibre: 9 },
    flavourTags: ['Smoky', 'Tangy', 'Nutty'],
    textureTags: ['Charred', 'Creamy', 'Crunchy'],
    isPublic: true,
    createdBy: 'LP',
    source: 'manual',
    createdAt: '2026-04-06T18:30:00Z',
    notes: 'My go-to weeknight dinner. Works with broccoli too.',
  },
  {
    id: 'user-black-bean-tacos',
    title: 'Smoky Black Bean Tacos with Lime Crema',
    cuisine: ['Mexican'],
    dietary: ['Vegetarian'],
    time: 25,
    difficulty: 1,
    matchScore: 0,
    description: 'Spiced black beans in warm corn tortillas topped with quick-pickled red onion, fresh coriander, and a tangy lime crema. Ready in under 30 minutes.',
    servings: 3,
    ingredients: [
      { name: 'Black beans (tinned)', amount: '400', unit: 'g' },
      { name: 'Corn tortillas', amount: '6', unit: 'small' },
      { name: 'Smoked paprika', amount: '1', unit: 'tsp' },
      { name: 'Cumin', amount: '1', unit: 'tsp' },
      { name: 'Soured cream', amount: '4', unit: 'tbsp' },
      { name: 'Lime', amount: '1', unit: 'whole' },
      { name: 'Red onion', amount: '1', unit: 'small' },
      { name: 'Fresh coriander', amount: '1', unit: 'bunch' },
      { name: 'Avocado', amount: '1', unit: 'ripe' },
    ],
    steps: [
      { number: 1, instruction: 'Thinly slice the red onion and quick-pickle in lime juice and a pinch of salt for 15 minutes.', techniqueTags: ['Pickling'] },
      { number: 2, instruction: 'Drain and rinse the beans. Heat in a pan with smoked paprika, cumin, and a splash of water. Mash roughly.', techniqueTags: ['Sautéing'] },
      { number: 3, instruction: 'Mix soured cream with lime zest and a squeeze of juice.', techniqueTags: ['Mixing'] },
      { number: 4, instruction: 'Warm the tortillas in a dry pan until pliable and lightly charred.', techniqueTags: ['Toasting'] },
      { number: 5, instruction: 'Assemble: beans, sliced avocado, pickled onion, lime crema, and fresh coriander.', techniqueTags: ['Plating'] },
    ],
    nutrition: { calories: 380, protein: 14, carbs: 48, fat: 15, fibre: 12 },
    flavourTags: ['Smoky', 'Tangy', 'Fresh'],
    textureTags: ['Creamy', 'Crunchy', 'Soft'],
    isPublic: false,
    createdBy: 'LP',
    source: 'ai-generated',
    createdAt: '2026-04-07T12:15:00Z',
  },
];

// Default empty recipe for the form
export const emptyRecipe: Omit<UserRecipe, 'id' | 'createdAt'> = {
  title: '',
  cuisine: [],
  dietary: [],
  time: 30,
  difficulty: 1,
  matchScore: 0,
  description: '',
  servings: 2,
  ingredients: [],
  steps: [],
  nutrition: { calories: 0, protein: 0, carbs: 0, fat: 0, fibre: 0 },
  flavourTags: [],
  textureTags: [],
  isPublic: false,
  createdBy: 'LP',
  source: 'manual',
};

export const cuisineOptions = ['Japanese', 'Italian', 'Thai', 'Mexican', 'Indian', 'French', 'Korean', 'Mediterranean', 'Middle Eastern', 'Chinese', 'Vietnamese', 'Greek', 'Spanish', 'North African', 'Caribbean'];
export const dietaryOptions = ['Vegan', 'Vegetarian', 'Gluten-Free', 'Dairy-Free', 'Nut-Free', 'Halal', 'Pescatarian'];
