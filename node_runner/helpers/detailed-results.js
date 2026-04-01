class detailedResults {
    explicitPass = false;
    explicitFail = false;
    explicitNotApplicable = false;

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

    forceNotApplicable() {
        this.explicitNotApplicable = true;
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

    status() {
        if (this.explicitNotApplicable) {
            return 'na';
        }
        if (this.explicitPass) {
            return 'pass';
        }
        if (this.explicitFail) {
            return 'fail';
        }
        return this.failedElements.length === 0 ? 'pass' : 'fail';
    }

    passed() {
        return this.status() === 'pass';
    }
}
module.exports = detailedResults;