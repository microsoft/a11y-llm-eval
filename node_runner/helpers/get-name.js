const getName = async (el) => {
    return await el.evaluate((el) => {
        return window.axe.commons.text.accessibleText(el);
    });
}

module.exports = getName;