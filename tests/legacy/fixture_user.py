"""A small collection shaped like the user's: same note types, field names and decks."""
import os, tempfile
from anki.collection import Collection

TYPES = {
    "CC-CEDICT Optimized EN v5.3": ["EntryKey", "Simplified", "Traditional", "PinyinMarked", "DefinitionsHTML", "MeaningPromptHTML", "ExampleSentence", "ExampleTranslation", "HSK", "Notizen"],
    "JP Vocabulary · 2-way (JMdict)": ["EntryID", "Word", "Reading", "MainMeaning", "AllDefinitions", "ExampleJP", "ExampleEN", "PersonalNotes"],
    "Vietnamese Optimized EN v7": ["Vietnamese", "English", "ExampleVietnamese", "ExampleEnglish", "Notizen"],
    "Heisig – Schreiben (einfach)": ["Sortierung", "Zeichen", "Schluesselwort", "Eigene_Merkhilfe"],
}

def _type(col, name, fields):
    mm = col.models
    m = mm.new(name)
    for f in fields:
        mm.add_field(m, mm.new_field(f))
    t = mm.new_template("Card 1")
    t["qfmt"] = "{{%s}}" % fields[1]
    t["afmt"] = "{{FrontSide}}"
    mm.add_template(m, t)
    mm.add(m)
    return mm.by_name(name)

CN = "Language::中文::CC-CEDICT Optimized EN"
CN_A = "Language::中文::詞彙::a. 孫悟空"
JP = "Language::日本語::日本語 Vocabulary"
VI = "Language::Vietnamese::Vietnamese Optimized Dictionary"
HE = "Heisig::Chinesisch – Vereinfacht – Schreiben (3018)"

ROWS = [
    # key, type, deck, fields
    ("ni", "CC-CEDICT Optimized EN v5.3", CN_A, {"Simplified": "你", "Traditional": "你", "MeaningPromptHTML": '<span class="pinyin">nǐ</span> you', "ExampleSentence": "你好吗？"}),
    ("nihao", "CC-CEDICT Optimized EN v5.3", CN_A, {"Simplified": "你好", "Traditional": "你好", "MeaningPromptHTML": "hello"}),
    ("nimen", "CC-CEDICT Optimized EN v5.3", CN, {"Simplified": "你们", "Traditional": "你們", "MeaningPromptHTML": "you (plural)"}),
    ("hao", "CC-CEDICT Optimized EN v5.3", CN, {"Simplified": "好", "Traditional": "好", "MeaningPromptHTML": "good; well"}),
    ("haoren", "CC-CEDICT Optimized EN v5.3", CN, {"Simplified": "好人", "Traditional": "好人", "MeaningPromptHTML": "good person"}),
    ("yangguang", "CC-CEDICT Optimized EN v5.3", CN, {"Simplified": "阳光", "Traditional": "陽光", "MeaningPromptHTML": "sunshine"}),
    ("chi", "CC-CEDICT Optimized EN v5.3", CN, {"Simplified": "吃", "Traditional": "吃", "MeaningPromptHTML": "to eat", "ExampleSentence": "我们吃饭吧，你好"}),
    ("weida", "CC-CEDICT Optimized EN v5.3", CN, {"Simplified": "伟大", "Traditional": "偉大", "MeaningPromptHTML": "great; mighty", "DefinitionsHTML": "great; theater of eat"}),
    ("taberu", "JP Vocabulary · 2-way (JMdict)", JP, {"EntryID": "1358280", "Word": "食べる", "Reading": "たべる", "MainMeaning": "to eat"}),
    ("ara", "JP Vocabulary · 2-way (JMdict)", JP, {"EntryID": "1000525", "Word": "𩺊", "Reading": "あら", "MainMeaning": "saw-edged perch"}),
    ("nihonjin", "JP Vocabulary · 2-way (JMdict)", JP, {"EntryID": "1", "Word": "好人物", "Reading": "こうじんぶつ", "MainMeaning": "good-natured person"}),
    ("cu", "Vietnamese Optimized EN v7", VI, {"Vietnamese": "cứ", "English": "just; keep on"}),
    ("cuviec", "Vietnamese Optimized EN v7", VI, {"Vietnamese": "cứ việc", "English": "go ahead"}),
    ("cuu", "Vietnamese Optimized EN v7", VI, {"Vietnamese": "cứu", "English": "to save"}),
    ("vieclam", "Vietnamese Optimized EN v7", VI, {"Vietnamese": "việc làm", "English": "job"}),
    ("lamviec", "Vietnamese Optimized EN v7", VI, {"Vietnamese": "làm việc", "English": "to work"}),
    ("an", "Vietnamese Optimized EN v7", VI, {"Vietnamese": "ăn", "English": "to eat", "ExampleEnglish": "eat a great meal"}),
    ("he_hao", "Heisig – Schreiben (einfach)", HE, {"Sortierung": "97", "Zeichen": "好", "Schluesselwort": "good"}),
]

def make():
    col = Collection(os.path.join(tempfile.mkdtemp(), "user.anki2"))
    types = {name: _type(col, name, flds) for name, flds in TYPES.items()}
    ids = {}
    for key, tname, deck, values in ROWS:
        note = col.new_note(types[tname])
        for f, v in values.items():
            note[f] = v
        col.add_note(note, col.decks.id(deck))
        ids[key] = note.id
    return col, ids
