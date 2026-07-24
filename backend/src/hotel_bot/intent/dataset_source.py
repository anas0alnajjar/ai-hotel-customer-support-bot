"""Explicit bilingual scenario source for intent dataset v1.0.0."""

from hotel_bot.domain.intent.enums import DatasetSplit, IntentCode
from hotel_bot.domain.intent.models import IntentDataset, IntentSample
from hotel_bot.domain.intent.taxonomy import TAXONOMY_VERSION

DATASET_VERSION = "intent-dataset-v1.0.0"

# Each pair is one scenario expressed independently in Arabic and English. Indices 1-6
# are training, 7-8 validation, and 9-12 held-out test scenarios.
SCENARIOS: dict[IntentCode, tuple[tuple[str, str], ...]] = {
    IntentCode.HOTEL_INFO: (
        ("ما هي المرافق الموجودة في الفندق؟", "What facilities does the hotel have?"),
        ("أين يقع فندق نور الشام؟", "Where is Nour Al-Sham hotel located?"),
        ("ما هو وقت تسجيل الدخول؟", "What time is check-in?"),
        ("متى يجب تسجيل المغادرة؟", "When is check-out time?"),
        ("هل تتوفر خدمة واي فاي في الفندق؟", "Does the hotel provide Wi-Fi?"),
        ("هل الإفطار مشمول وما هي مواعيده؟", "Is breakfast included and when is it served?"),
        ("هل يوجد موقف سيارات للنزلاء؟", "Is guest parking available?"),
        ("هل يسمح الفندق باصطحاب الحيوانات؟", "What is the hotel's pet policy?"),
        ("ما هي ساعات عمل المسبح؟", "What are the swimming pool opening hours?"),
        ("كم يبعد الفندق عن المطار؟", "How far is the hotel from the airport?"),
        ("هل التدخين مسموح داخل الفندق؟", "Is smoking allowed inside the hotel?"),
        ("ما هي سياسة المغادرة المتأخرة؟", "What is the late check-out policy?"),
    ),
    IntentCode.ROOM_TYPES: (
        ("ما هي أنواع الغرف الموجودة لديكم؟", "Which room categories do you offer?"),
        ("أخبرني عن مواصفات الغرفة الديلوكس", "Tell me the features of a deluxe room"),
        ("هل لديكم أجنحة فندقية؟", "Do you have hotel suites?"),
        ("أريد معلومات عن الغرفة العائلية", "I need information about the family room"),
        ("ما خيارات الأسرّة في الغرف؟", "What bed options are available in the rooms?"),
        ("هل توجد غرف مهيأة لذوي الإعاقة؟", "Are accessible rooms available?"),
        ("أي أنواع الغرف تطل على المدينة؟", "Which room types have a city view?"),
        ("كم شخصاً تستوعب كل فئة غرفة؟", "How many guests can each room type hold?"),
        ("ما هي أبسط فئة غرفة لديكم؟", "What is your most basic room category?"),
        ("أي غرفة تحتوي على شرفة؟", "Which room category includes a balcony?"),
        ("صف لي الغرفة التنفيذية", "Describe the executive room type"),
        ("قارن بين مساحات أنواع الغرف", "Compare the sizes of your room categories"),
    ),
    IntentCode.ROOM_AVAILABILITY: (
        ("هل توجد غرفة متاحة الليلة؟", "Is there a room available tonight?"),
        ("تحقق من التوفر من 10 إلى 13 آب", "Check availability from August 10 to 13"),
        ("هل توجد غرفة لعائلة من أربعة أشخاص؟", "Is a room available for a family of four?"),
        ("أحتاج غرفة لشخصين الأسبوع القادم", "I need an available room for two next week"),
        ("ما الغرف الشاغرة في عطلة نهاية الأسبوع؟", "What rooms are vacant this weekend?"),
        ("ابحث عن غرفة متاحة الشهر القادم", "Find an available room next month"),
        (
            "هل يمكنني الإقامة ثلاث ليال ابتداء من الأحد؟",
            "Can I stay three nights starting Sunday?",
        ),
        ("هل لديكم غرفة شاغرة لنزيل واحد؟", "Do you have a vacant room for one guest?"),
        (
            "تحقق من غرفة متاحة لشهر العسل في أيلول",
            "Check room availability for a September honeymoon",
        ),
        ("هل بقيت أي غرف للغد؟", "Are any rooms left for tomorrow?"),
        ("أحتاج غرفتين متاحتين لثلاثة بالغين", "I need two available rooms for three adults"),
        ("ما التوفر خلال عطلة العيد؟", "What availability do you have over the holiday?"),
    ),
    IntentCode.BOOKING_LOOKUP: (
        ("أريد العثور على حجزي باستخدام الرقم", "I want to find my booking by reference"),
        ("اعرض لي تفاصيل الحجز NSH1001", "Show me the details of booking NSH1001"),
        ("هل حجزي مؤكد؟", "Can you confirm whether my reservation exists?"),
        ("ما تواريخ الإقامة المسجلة في حجزي؟", "What stay dates are recorded on my booking?"),
        ("أريد معرفة حالة الحجز الحالي", "I need the status of my current booking"),
        ("هل تم تعيين غرفة لحجزي؟", "Has a room been assigned to my reservation?"),
        ("ساعدني في مراجعة بيانات حجزي", "Help me review my reservation details"),
        ("ابحث عن الحجز المرتبط بهذا المرجع", "Look up the reservation linked to this reference"),
        ("تحقق من مرجع الحجز NSH2045", "Check booking reference NSH2045"),
        ("هل يوجد حجز مسجل باسمي؟", "Is there a reservation registered for me?"),
        ("ما رقم الغرفة المحجوزة لي؟", "Which room number is assigned to my booking?"),
        ("أظهر معلومات الوصول الموجودة في حجزي", "Show the arrival information on my reservation"),
    ),
    IntentCode.ROOM_SERVICE_REQUEST: (
        ("أريد طلب وجبة إلى الغرفة", "I would like to order food to my room"),
        ("أرسلوا مناشف إضافية إلى غرفتي", "Please send extra towels to my room"),
        ("أحتاج خدمة تنظيف الغرفة", "I need housekeeping for my room"),
        ("هل يمكن إحضار مياه شرب؟", "Could you bring drinking water to the room?"),
        ("أريد وسادتين إضافيتين", "Please deliver two extra pillows"),
        ("أرسلوا الإفطار إلى الغرفة", "Send breakfast to my room"),
        ("نحتاج مستلزمات استحمام إضافية", "We need additional toiletries"),
        ("يرجى تعبئة الميني بار", "Please restock the minibar"),
        ("أود طلب العشاء إلى الغرفة 305", "I want dinner delivered to room 305"),
        ("أرسلوا بطانية إضافية من فضلكم", "Please send an extra blanket"),
        ("أريد ترتيب تنظيف غرفتي الآن", "I want my room cleaned now"),
        ("هل يمكن توفير سرير طفل للغرفة؟", "Can you provide a baby crib for the room?"),
    ),
    IntentCode.MAINTENANCE_REQUEST: (
        ("المكيف في الغرفة لا يعمل", "The air conditioner in my room is not working"),
        ("يوجد تسريب مياه من الصنبور", "Water is leaking from the faucet"),
        ("التلفاز معطل وأحتاج فني صيانة", "The television is broken and needs maintenance"),
        ("مصباح الغرفة لا يضيء", "The room light will not turn on"),
        ("الخزنة الإلكترونية لا تفتح", "The electronic safe will not open"),
        ("الدش في الحمام لا يعمل", "The bathroom shower is not working"),
        ("ثلاجة الغرفة لا تبرد", "The room refrigerator is not cooling"),
        ("قفل باب الغرفة فيه عطل", "The room door lock is malfunctioning"),
        ("لا توجد مياه ساخنة في الحمام", "There is no hot water in the bathroom"),
        ("نافذة الغرفة مكسورة", "The room window is broken"),
        ("مقبس الكهرباء لا يعمل", "The electrical outlet is not working"),
        ("المرحاض مسدود ونحتاج صيانة", "The toilet is clogged and needs repair"),
    ),
    IntentCode.SERVICE_REQUEST_STATUS: (
        ("أريد تتبع طلب الخدمة الخاص بي", "I want to track my service request"),
        ("ما حالة طلب الصيانة SR100؟", "What is the status of maintenance request SR100?"),
        ("أين وصل طلب خدمة الغرف؟", "What is happening with my room service request?"),
        ("هل تم إنجاز الطلب الذي قدمته؟", "Has the request I submitted been completed?"),
        ("أريد متابعة البلاغ السابق", "I want to follow up on my previous request"),
        ("أعطني آخر تحديث على طلب الخدمة", "Give me the latest update on my service request"),
        ("كم بقي لوصول عامل الصيانة؟", "How long until maintenance arrives for my request?"),
        ("هل ما زال طلبي قيد الانتظار؟", "Is my service request still pending?"),
        ("هل الفني قادم لمعالجة الطلب؟", "Is the technician coming for my request?"),
        ("تحقق من حالة رمز الطلب SR245", "Check the status of request code SR245"),
        ("هل اكتملت خدمة التنظيف التي طلبتها؟", "Was my housekeeping request completed?"),
        ("أحتاج تحديثاً عن طلب المناشف", "I need a status update on my towel request"),
    ),
    IntentCode.HUMAN_ESCALATION: (
        ("أريد التحدث مع موظف حقيقي", "I want to speak with a human agent"),
        ("حولني إلى موظف الاستقبال", "Transfer me to reception"),
        ("أحتاج التحدث مع مدير الفندق", "I need to speak to the hotel manager"),
        ("لدي شكوى وأريد شخصاً مسؤولاً", "I have a complaint and want a responsible person"),
        ("اطلب من أحد الموظفين الاتصال بي", "Ask a staff member to call me"),
        ("أريد دعماً مباشراً من إنسان", "I need live support from a person"),
        ("هل يمكنك تحويلي إلى قسم خدمة العملاء؟", "Can you transfer me to customer service?"),
        ("لا أريد روبوتاً أريد شخصاً", "I do not want a bot; I want a real person"),
        ("أريد رفع الموضوع إلى المشرف", "I want to escalate this to a supervisor"),
        ("اجعل أحد موظفي الفندق يكلمني", "Have a hotel staff member talk to me"),
        ("أحتاج مساعدة بشرية عاجلة", "I need urgent human assistance"),
        ("اربطني بممثل خدمة وليس روبوتاً", "Connect me with a service representative, not a bot"),
    ),
    IntentCode.GREETING_SMALLTALK: (
        ("مرحبا", "Hello"),
        ("صباح الخير", "Good morning"),
        ("كيف حالك اليوم؟", "How are you today?"),
        ("مساء الخير يا مساعد الفندق", "Good evening, hotel assistant"),
        ("شكراً جزيلاً لمساعدتك", "Thank you very much for your help"),
        ("إلى اللقاء", "Goodbye"),
        ("سعيد بالتحدث معك", "Nice to meet you"),
        ("يعطيك العافية وشكراً", "Thanks, I appreciate it"),
        ("تصبح على خير", "Good night"),
        ("أهلاً يا صديقي", "Hey there"),
        ("السلام عليكم ورحمة الله", "Peace be upon you"),
        ("ممتن جداً لخدمتك", "I really appreciate your assistance"),
    ),
    IntentCode.UNSUPPORTED: (
        ("ما توقعات الطقس في أوروبا؟", "What is the weather forecast in Europe?"),
        ("احجز لي تذكرة طيران", "Book an airline ticket for me"),
        ("أعطني نصيحة لتداول العملات", "Give me currency trading advice"),
        ("شخّص لي هذه الأعراض الطبية", "Diagnose these medical symptoms for me"),
        ("حل لي واجب الرياضيات", "Solve my mathematics homework"),
        ("من سيفوز بكأس العالم؟", "Who will win the World Cup?"),
        ("اكتب لي وصفة طبخ للمعكرونة", "Write me a pasta recipe"),
        ("ما رأيك في الانتخابات؟", "What do you think about the election?"),
        ("ساعدني في شراء العملات الرقمية", "Help me buy cryptocurrency"),
        ("قدم لي استشارة قانونية لقضيتي", "Give me legal advice for my court case"),
        (
            "ترجم لي وثيقة طويلة لا علاقة لها بالفندق",
            "Translate a long document unrelated to the hotel",
        ),
        ("ابحث لي عن متجر إلكتروني للملابس", "Find me an online clothing store"),
    ),
}


def build_dataset() -> IntentDataset:
    samples: list[IntentSample] = []
    for intent in IntentCode:
        scenarios = SCENARIOS[intent]
        if len(scenarios) != 12:
            raise ValueError(f"{intent.value} must define exactly 12 scenarios")
        for index, (arabic, english) in enumerate(scenarios, start=1):
            split = (
                DatasetSplit.TRAIN
                if index <= 6
                else DatasetSplit.VALIDATION
                if index <= 8
                else DatasetSplit.TEST
            )
            scenario_id = f"{intent.value}-{index:02d}"
            samples.extend(
                (
                    IntentSample(
                        id=f"{scenario_id}-ar",
                        scenario_id=scenario_id,
                        split=split,
                        language="ar",
                        text=arabic,
                        intent=intent,
                    ),
                    IntentSample(
                        id=f"{scenario_id}-en",
                        scenario_id=scenario_id,
                        split=split,
                        language="en",
                        text=english,
                        intent=intent,
                    ),
                )
            )
    return IntentDataset(
        dataset_version=DATASET_VERSION,
        taxonomy_version=TAXONOMY_VERSION,
        description=(
            "Synthetic bilingual hotel-support intent baseline split by scenario; "
            "not a substitute for real guest-language validation."
        ),
        samples=tuple(samples),
    )
