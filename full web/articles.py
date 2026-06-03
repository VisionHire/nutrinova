# articles.py
articles = [
    # articles.py (add this to the existing list)
{
    "slug": "calories-in-roti",
    "title": "Calories in Roti: Complete Nutrition Guide",
    "date": "2026-06-01",            # Today’s date – change as needed
    "modified": "2026-06-03",
    "description": "Find out how many calories are in one roti, its full nutritional value, and whether roti is good for weight loss. Your complete Indian diet guide.",
    "image": "/static/data/roti.jpg",   # Place an image here
    "tags": ["calories", "roti", "indian-diet", "weight-loss"],
    "faq": [
        {"question": "How many calories are in 2 rotis?", "answer": "Two medium plain wheat rotis (without ghee) contain approximately 140–160 calories. With ghee, 220–260 calories."},
        {"question": "Is roti healthier than rice?", "answer": "Both are healthy. Roti has more fibre and is slightly lower in calories per serving, but the overall diet matters more."},
        {"question": "Can I eat roti during weight loss?", "answer": "Yes, roti is filling and portion‑friendly. Stick to 2–3 medium rotis with little ghee and pair with vegetables or dal."},
        {"question": "Which flour has the lowest calories?", "answer": "Whole wheat atta, jowar, and bajra are among the lowest in calories while offering good fibre."}
    ]
},
    # Add more articles here as you write them
]

def get_all_articles():
    return sorted(articles, key=lambda x: x["date"], reverse=True)

def get_article_by_slug(slug):
    return next((a for a in articles if a["slug"] == slug), None)