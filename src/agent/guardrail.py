"""Bedrock Guardrails applied to what the customer sends and to what the agent says."""
import os

import boto3

_bedrock = boto3.client("bedrock-runtime")

SAFE_REPLY = {
    "en": "I can only help with your motor insurance claim. If you would like to speak to a person, just say so and an adjuster will contact you.",
    "ta": "மன்னிக்கவும், வாகனக் காப்பீட்டுக் கோரிக்கை தொடர்பான விவரங்களில் மட்டுமே எங்களால் உதவ முடியும். ஒருவருடன் பேச விரும்பினால் தெரிவிக்கவும்; காப்பீட்டு நிறுவன அலுவலர் உங்களைத் தொடர்பு கொள்வார்.",
    "hi": "मैं केवल आपके मोटर बीमा क्लेम में मदद कर सकता हूँ। किसी व्यक्ति से बात करनी हो तो बताइए, एडजस्टर आपसे संपर्क करेगा।",
    "te": "క్షమించండి, మీ వాహన బీమా క్లెయిమ్‌కు సంబంధించిన విషయాల్లో మాత్రమే మేము సహాయం చేయగలము. ఒకరితో మాట్లాడాలనుకుంటే తెలియజేయండి; క్లెయిమ్ అధికారి (అడ్జస్టర్) మిమ్మల్ని సంప్రదిస్తారు.",
    "ml": "ക്ഷമിക്കണം, നിങ്ങളുടെ വാഹന ഇൻഷുറൻസ് ക്ലെയിമുമായി ബന്ധപ്പെട്ട കാര്യങ്ങളിൽ മാത്രമേ ഞങ്ങൾക്ക് സഹായിക്കാൻ കഴിയൂ. ഒരാളോട് സംസാരിക്കണമെങ്കിൽ അറിയിക്കുക; ക്ലെയിം ഉദ്യോഗസ്ഥൻ (അഡ്ജസ്റ്റർ) നിങ്ങളെ ബന്ധപ്പെടും.",
    "kn": "ಕ್ಷಮಿಸಿ, ನಿಮ್ಮ ವಾಹನ ವಿಮೆ ಕ್ಲೇಮ್‌ಗೆ ಸಂಬಂಧಿಸಿದ ವಿಷಯಗಳಲ್ಲಿ ಮಾತ್ರ ನಾವು ಸಹಾಯ ಮಾಡಬಹುದು. ಒಬ್ಬರೊಂದಿಗೆ ಮಾತನಾಡಲು ಬಯಸಿದರೆ ತಿಳಿಸಿ; ಕ್ಲೇಮ್ ಅಧಿಕಾರಿ (ಅಡ್ಜಸ್ಟರ್) ನಿಮ್ಮನ್ನು ಸಂಪರ್ಕಿಸುತ್ತಾರೆ.",
}


def allowed(source: str, text: str) -> bool:
    """source is 'INPUT' (customer text) or 'OUTPUT' (agent reply). True when nothing was blocked."""
    guardrail_id = os.environ.get("GUARDRAIL_ID")
    if not guardrail_id or not text.strip():
        return True
    resp = _bedrock.apply_guardrail(
        guardrailIdentifier=guardrail_id,
        guardrailVersion=os.environ.get("GUARDRAIL_VERSION", "DRAFT"),
        source=source,
        content=[{"text": {"text": text[:4000]}}],
    )
    return resp["action"] != "GUARDRAIL_INTERVENED"


def safe_reply(language: str = "en") -> str:
    return SAFE_REPLY.get(language, SAFE_REPLY["en"])
