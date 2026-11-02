// Labels for the printed trip sheet: English plus the cost center's regional language (setting print_language).
// Translations are a first draft - have a native speaker check them before the sheets go to drivers.
export const LANGUAGES = { "": "English only", te: "Telugu", kn: "Kannada", ta: "Tamil", hi: "Hindi" };

const T = {
  title: { en: "Trip sheet", te: "ట్రిప్ షీట్", kn: "ಟ್ರಿಪ್ ಶೀಟ್", ta: "பயணத் தாள்", hi: "ट्रिप शीट" },
  depot: { en: "Depot", te: "డిపో", kn: "ಡಿಪೋ", ta: "பணிமனை", hi: "डिपो" },
  bus: { en: "Bus no.", te: "బస్సు నెం.", kn: "ಬಸ್ ಸಂ.", ta: "பேருந்து எண்", hi: "बस नं." },
  registration: { en: "Registration", te: "రిజిస్ట్రేషన్", kn: "ನೋಂದಣಿ", ta: "பதிவு எண்", hi: "पंजीकरण" },
  schedule: { en: "Schedule", te: "షెడ్యూల్", kn: "ವೇಳಾಪಟ್ಟಿ", ta: "அட்டவணை", hi: "शेड्यूल" },
  date: { en: "Date", te: "తేదీ", kn: "ದಿನಾಂಕ", ta: "தேதி", hi: "दिनांक" },
  sheetNo: { en: "Sheet no.", te: "షీట్ నెం.", kn: "ಶೀಟ್ ಸಂ.", ta: "தாள் எண்", hi: "शीट नं." },
  crew: { en: "Crew", te: "సిబ్బంది", kn: "ಸಿಬ್ಬಂದಿ", ta: "பணியாளர்கள்", hi: "कर्मीदल" },
  DRIVER: { en: "Driver", te: "డ్రైవర్", kn: "ಚಾಲಕ", ta: "ஓட்டுநர்", hi: "चालक" },
  CONDUCTOR: { en: "Conductor", te: "కండక్టర్", kn: "ನಿರ್ವಾಹಕ", ta: "நடத்துநர்", hi: "परिचालक" },
  shift: { en: "Shift", te: "షిఫ్ట్", kn: "ಪಾಳಿ", ta: "பணிமுறை", hi: "पाली" },
  name: { en: "Name", te: "పేరు", kn: "ಹೆಸರು", ta: "பெயர்", hi: "नाम" },
  empNo: { en: "Emp. no.", te: "ఉద్యోగి నెం.", kn: "ನೌಕರ ಸಂ.", ta: "பணியாளர் எண்", hi: "कर्मचारी नं." },
  dutyFrom: { en: "Duty from", te: "డ్యూటీ ప్రారంభం", kn: "ಕರ್ತವ್ಯ ಆರಂಭ", ta: "பணி தொடக்கம்", hi: "ड्यूटी आरंभ" },
  dutyTo: { en: "Duty to", te: "డ్యూటీ ముగింపు", kn: "ಕರ್ತವ್ಯ ಮುಕ್ತಾಯ", ta: "பணி முடிவு", hi: "ड्यूटी समाप्त" },
  signature: { en: "Signature", te: "సంతకం", kn: "ಸಹಿ", ta: "கையொப்பம்", hi: "हस्ताक्षर" },
  change: { en: "Driver change", te: "డ్రైవర్ మార్పు", kn: "ಚಾಲಕ ಬದಲಾವಣೆ", ta: "ஓட்டுநர் மாற்றம்", hi: "चालक परिवर्तन" },
  time: { en: "Time", te: "సమయం", kn: "ಸಮಯ", ta: "நேரம்", hi: "समय" },
  newDriver: { en: "New driver", te: "కొత్త డ్రైవర్", kn: "ಹೊಸ ಚಾಲಕ", ta: "புதிய ஓட்டுநர்", hi: "नया चालक" },
  reason: { en: "Reason", te: "కారణం", kn: "ಕಾರಣ", ta: "காரணம்", hi: "कारण" },
  run: { en: "Run", te: "కార్యకలాపం", kn: "ಚಟುವಟಿಕೆ", ta: "செயல்பாடு", hi: "गतिविधि" },
  fromTo: { en: "From → To", te: "నుండి → వరకు", kn: "ಇಂದ → ಗೆ", ta: "இருந்து → வரை", hi: "से → तक" },
  planned: { en: "Planned", te: "ప్రణాళిక", kn: "ಯೋಜಿತ", ta: "திட்டமிட்டது", hi: "नियोजित" },
  departed: { en: "Departed", te: "బయలుదేరిన సమయం", kn: "ಹೊರಟ ಸಮಯ", ta: "புறப்பட்ட நேரம்", hi: "प्रस्थान" },
  arrived: { en: "Arrived", te: "చేరిన సమయం", kn: "ತಲುಪಿದ ಸಮಯ", ta: "வந்தடைந்த நேரம்", hi: "आगमन" },
  odoStart: { en: "Odo start", te: "ఓడోమీటర్ ప్రారంభం", kn: "ಓಡೋಮೀಟರ್ ಆರಂಭ", ta: "ஓடோமீட்டர் தொடக்கம்", hi: "ओडोमीटर आरंभ" },
  odoEnd: { en: "Odo end", te: "ఓడోమీటర్ ముగింపు", kn: "ಓಡೋಮೀಟರ್ ಅಂತ್ಯ", ta: "ஓடோமீட்டர் முடிவு", hi: "ओडोमीटर समाप्त" },
  soc: { en: "SOC %", te: "బ్యాటరీ %", kn: "ಬ್ಯಾಟರಿ %", ta: "பேட்டரி %", hi: "बैटरी %" },
  remarks: { en: "Reason code / remarks", te: "కారణ కోడ్ / వ్యాఖ్యలు", kn: "ಕಾರಣ ಸಂಕೇತ / ಷರಾ", ta: "காரணக் குறியீடு / குறிப்புகள்", hi: "कारण कोड / टिप्पणी" },
  reasonCodes: { en: "Reason codes", te: "కారణ కోడ్‌లు", kn: "ಕಾರಣ ಸಂಕೇತಗಳು", ta: "காரணக் குறியீடுகள்", hi: "कारण कोड" },
  supervisor: { en: "Depot supervisor", te: "డిపో సూపర్‌వైజర్", kn: "ಡಿಪೋ ಮೇಲ್ವಿಚಾರಕ", ta: "பணிமனை மேற்பார்வையாளர்", hi: "डिपो पर्यवेक्षक" },
  PASSENGER_TRIP: { en: "Trip", te: "ట్రిప్", kn: "ಟ್ರಿಪ್", ta: "பயணம்", hi: "ट्रिप" },
  NON_REVENUE_MOVEMENT: { en: "Empty run", te: "ఖాళీ ప్రయాణం", kn: "ಖಾಲಿ ಸಂಚಾರ", ta: "காலி இயக்கம்", hi: "खाली संचालन" },
  CHARGING: { en: "Charging", te: "ఛార్జింగ్", kn: "ಚಾರ್ಜಿಂಗ್", ta: "மின்னேற்றம்", hi: "चार्जिंग" },
  LAYOVER: { en: "Layover", te: "విరామం", kn: "ವಿರಾಮ", ta: "இடைநிறுத்தம்", hi: "ठहराव" },
  HALT: { en: "Halt", te: "నిలుపుదల", kn: "ತಂಗುವಿಕೆ", ta: "நிறுத்தம்", hi: "पड़ाव" },
  ran: { en: "Ran", te: "నడిచింది", kn: "ಓಡಿತು", ta: "இயங்கியது", hi: "चली" },
  cut: { en: "Cut", te: "మధ్యలో ఆగింది", kn: "ಮಧ್ಯದಲ್ಲಿ ನಿಂತಿತು", ta: "இடையில் நின்றது", hi: "बीच में रुकी" },
  notRun: { en: "Not", te: "నడవలేదు", kn: "ಓಡಲಿಲ್ಲ", ta: "இயங்கவில்லை", hi: "नहीं चली" },
  status: { en: "Tick one", te: "ఒకటి టిక్ చేయండి", kn: "ಒಂದನ್ನು ಗುರುತಿಸಿ", ta: "ஒன்றைக் குறிக்கவும்", hi: "एक पर टिक करें" },
  reasonNo: { en: "Reason #", te: "కారణ సంఖ్య", kn: "ಕಾರಣ ಸಂಖ್ಯೆ", ta: "காரண எண்", hi: "कारण संख्या" },
  endStop: { en: "Stop #", te: "ఆగిన స్టాప్", kn: "ನಿಂತ ನಿಲ್ದಾಣ", ta: "நின்ற நிறுத்தம்", hi: "रुकने का स्टॉप" },
  autoFilled: { en: "filled in the office", te: "కార్యాలయంలో నింపబడుతుంది", kn: "ಕಚೇರಿಯಲ್ಲಿ ತುಂಬಲಾಗುತ್ತದೆ", ta: "அலுவலகத்தில் நிரப்பப்படும்", hi: "कार्यालय में भरा जाएगा" },
  howTo: {
    en: "Write clearly inside each cell. Times in 24-hour (e.g. 18:35, not 6:35). Tick one of Ran / Cut short / Not run. Odometer in whole km. Reason # and Stop # come from the lists at the foot.",
    te: "ప్రతి గడిలో స్పష్టంగా రాయండి. సమయం 24 గంటల పద్ధతిలో (ఉదా. 18:35, 6:35 కాదు). నడిచింది / మధ్యలో ఆగింది / నడవలేదు - ఒకటి టిక్ చేయండి. ఓడోమీటర్ పూర్తి కిలోమీటర్లలో. కారణ సంఖ్య, ఆగిన స్టాప్ సంఖ్య కింది జాబితాల నుండి.",
    kn: "ಪ್ರತಿ ಕೋಶದಲ್ಲಿ ಸ್ಪಷ್ಟವಾಗಿ ಬರೆಯಿರಿ. ಸಮಯ 24 ಗಂಟೆಯ ಕ್ರಮದಲ್ಲಿ (ಉದಾ. 18:35). ಓಡಿತು / ಮಧ್ಯದಲ್ಲಿ ನಿಂತಿತು / ಓಡಲಿಲ್ಲ - ಒಂದನ್ನು ಗುರುತಿಸಿ. ಓಡೋಮೀಟರ್ ಪೂರ್ಣ ಕಿ.ಮೀ.",
    ta: "ஒவ்வொரு கட்டத்திலும் தெளிவாக எழுதவும். நேரம் 24 மணி முறையில் (எ.கா. 18:35). இயங்கியது / இடையில் நின்றது / இயங்கவில்லை - ஒன்றைக் குறிக்கவும். ஓடோமீட்டர் முழு கி.மீ.",
    hi: "हर खाने में साफ लिखें। समय 24 घंटे में (जैसे 18:35)। चली / बीच में रुकी / नहीं चली - एक पर निशान लगाएँ। ओडोमीटर पूरे कि.मी में।",
  },
  busChange: { en: "Bus change", te: "బస్సు మార్పు", kn: "ಬಸ್ ಬದಲಾವಣೆ", ta: "பேருந்து மாற்றம்", hi: "बस परिवर्तन" },
  newBusReg: { en: "Other bus registration (no spaces)", te: "వేరే బస్సు రిజిస్ట్రేషన్ (ఖాళీలు లేకుండా)", kn: "ಬೇರೆ ಬಸ್ ನೋಂದಣಿ (ಖಾಲಿ ಇಲ್ಲದೆ)", ta: "வேறு பேருந்து பதிவு எண் (இடைவெளி இல்லாமல்)", hi: "दूसरी बस पंजीकरण (बिना खाली जगह)" },
  fromRun: { en: "From run #", te: "ప్రయాణ సంఖ్య నుండి", kn: "ಚಟುವಟಿಕೆ ಸಂಖ್ಯೆಯಿಂದ", ta: "செயல் எண் முதல்", hi: "गतिविधि संख्या से" },
  discardOld: { en: "Use only while this version is current - discard when a new version is issued",
    te: "ఈ వెర్షన్ అమలులో ఉన్నంత వరకే వాడండి - కొత్త వెర్షన్ వచ్చినప్పుడు పాత షీట్లు వాడవద్దు",
    kn: "ಈ ಆವೃತ್ತಿ ಚಾಲ್ತಿಯಲ್ಲಿರುವವರೆಗೆ ಮಾತ್ರ ಬಳಸಿ - ಹೊಸ ಆವೃತ್ತಿ ಬಂದಾಗ ಹಳೆಯ ಶೀಟ್‌ಗಳನ್ನು ಬಳಸಬೇಡಿ",
    ta: "இந்தப் பதிப்பு நடைமுறையில் உள்ளவரை மட்டும் பயன்படுத்தவும் - புதிய பதிப்பு வந்ததும் பழைய தாள்களைப் பயன்படுத்த வேண்டாம்",
    hi: "केवल इस संस्करण के लागू रहने तक उपयोग करें - नया संस्करण आने पर पुरानी शीट का उपयोग न करें" },
  from: { en: "From", te: "ప్రారంభ స్థలం", kn: "ಇಂದ", ta: "இருந்து", hi: "से" },
  to: { en: "To", te: "గమ్య స్థలం", kn: "ಗೆ", ta: "வரை", hi: "तक" },
  startSoc: { en: "Start SOC %", te: "ప్రారంభం SOC %", kn: "ಆರಂಭ SOC %", ta: "தொடக்க SOC %", hi: "आरंभ SOC %" },
  endSoc: { en: "End SOC %", te: "ముగింపు SOC %", kn: "ಅಂತ್ಯ SOC %", ta: "முடிவு SOC %", hi: "अंत SOC %" },
  observations: { en: "Observations", te: "పరిశీలనలు", kn: "ಅವಲೋಕನಗಳು", ta: "கருத்துகள்", hi: "टिप्पणियाँ" },
  finalRunKm: { en: "Final run km", te: "మొత్తం నడిచిన కి.మీ", kn: "ಒಟ್ಟು ಓಡಿದ ಕಿ.ಮೀ", ta: "மொத்த ஓட்ட கி.மீ", hi: "कुल चली कि.मी" },
  deadKm: { en: "Dead km", te: "డెడ్ కి.మీ", kn: "ಡೆಡ್ ಕಿ.ಮೀ", ta: "டெட் கி.மீ", hi: "डेड कि.मी" },
  dutyCompleted: { en: "Duty completed", te: "డ్యూటీ పూర్తయింది", kn: "ಕರ್ತವ್ಯ ಪೂರ್ಣ", ta: "பணி முடிந்தது", hi: "ड्यूटी पूरी" },
  yes: { en: "Yes", te: "అవును", kn: "ಹೌದು", ta: "ஆம்", hi: "हाँ" },
  no: { en: "No", te: "కాదు", kn: "ಇಲ್ಲ", ta: "இல்லை", hi: "नहीं" },
  stationIncharge: { en: "Station incharge", te: "స్టేషన్ ఇన్‌ఛార్జి", kn: "ನಿಲ್ದಾಣ ಉಸ್ತುವಾರಿ", ta: "நிலைய பொறுப்பாளர்", hi: "स्टेशन प्रभारी" },
  operatorIncharge: { en: "Operator incharge", te: "ఆపరేటర్ ఇన్‌ఛార్జి", kn: "ಆಪರೇಟರ್ ಉಸ್ತುವಾರಿ", ta: "இயக்குநர் பொறுப்பாளர்", hi: "ऑपरेटर प्रभारी" },
  cancelled: { en: "Not run? write the reason code", te: "నడవలేదా? కారణ కోడ్ రాయండి", kn: "ಓಡಲಿಲ್ಲವೇ? ಕಾರಣ ಸಂಕೇತ ಬರೆಯಿರಿ", ta: "இயக்கவில்லையா? காரணக் குறியீட்டை எழுதவும்", hi: "नहीं चली? कारण कोड लिखें" },
};

// Regional names for the nine reason codes seeded for a new company, so the legend reads in both
// languages out of the box. A reason the depot adds or renames itself carries its own regional name
// (field reason_name_local), which wins over this fallback. Drafts - have them checked.
const REASONS = {
  BREAKDOWN: { te: "వాహనం మొరాయించింది", kn: "ವಾಹನ ಕೆಟ್ಟುಹೋಗಿದೆ", ta: "வாகனம் பாதிப்பு", hi: "वाहन खराब" },
  ACCIDENT: { te: "ప్రమాదం", kn: "ಅಪಘಾತ", ta: "விபத்து", hi: "दुर्घटना" },
  NO_CREW: { te: "డ్రైవర్ / సిబ్బంది లేరు", kn: "ಚಾಲಕ / ಸಿಬ್ಬಂದಿ ಇಲ್ಲ", ta: "ஓட்டுநர் / பணியாளர் இல்லை", hi: "चालक / कर्मीदल नहीं" },
  CHARGING: { te: "ఛార్జింగ్ సమస్య / తక్కువ SOC", kn: "ಚಾರ್ಜಿಂಗ್ ಸಮಸ್ಯೆ / ಕಡಿಮೆ SOC", ta: "விளித்தல் சிக்கல்", hi: "चार्जिंग समस्या" },
  TRAFFIC: { te: "ట్రాఫిక్ రద్దీ", kn: "ಸಂಚಾರ ದಟ್ಟಣೆ", ta: "போக்குவரத்து நெரிசல்", hi: "यातायात जाम" },
  ROAD_CLOSED: { te: "రోడ్డు మూసివేత / దారి మళ్లింపు", kn: "ರಸ್ತೆ ಬಂದ್ / ಮಾರ್ಗ ಬದಲಾವಣೆ", ta: "சாலை அடைப்பு / வழிமாற்றம்", hi: "सड़क बंद / मार्ग बदल" },
  WEATHER: { te: "వాతావరణం", kn: "ಹವಾಮಾನ", ta: "வானிலை", hi: "मौसम" },
  CLIENT: { te: "క్లయింట్ సూచన", kn: "ಗ್ರಾಹಕರ ಸೂಚನೆ", ta: "வாடிக்கைதாரர் அறிவுறுத்தல்", hi: "ग्राहक का निर्देश" },
  OTHER: { te: "ఇతర", kn: "ಇತರೆ", ta: "பிற", hi: "अन्य" },
};

/** Regional name for a reason: the one typed on the reason, else the seeded default's translation. */
export function reasonLocal(reason, lang) {
  return reason.name_local || (lang && REASONS[reason.code]?.[lang]) || null;
}

export const english = (key) => T[key]?.en || key;

/** Regional text alone (or null), for two-line headings. */
export function regional(key, lang) {
  return (lang && T[key]?.[lang]) || null;
}
