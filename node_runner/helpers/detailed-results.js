class detailedResults {
    explicitPass = false;
    explicitFail = false;

    constructor() {
        this.passedElements = [];
        this.failedElements = [];
        this.messages = [];
    }

    forcePass() {
        this.explicitPass = true;
    }

    forceFail() {
        this.explicitFail = true;
    }

    addPass(element) {
        this.passedElements.push(element);
    }
    
    addFail(element) {
        this.failedElements.push(element);
    }

    addMessage(message) {
        this.messages.push(message);
    }

    getMessage() {
        return this.messages.join(' ');
    }

    passed() {
        if (this.explicitPass) {
            return true;
        }
        if (this.explicitFail) {
            return false;
        }
        return this.failedElements.length === 0;
    }
}
module.exports = detailedResults;