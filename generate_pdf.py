from reportlab.pdfgen import canvas

def create_pdf(filename):
    c = canvas.Canvas(filename)
    c.drawString(100, 750, "Hello, this is a test PDF for the Company Data Processor.")
    c.drawString(100, 730, "We need to ensure text extraction works correctly.")
    c.drawString(100, 710, "1234567890 - Some numbers too.")
    c.save()

if __name__ == "__main__":
    create_pdf("sample.pdf")
    print("sample.pdf created")
